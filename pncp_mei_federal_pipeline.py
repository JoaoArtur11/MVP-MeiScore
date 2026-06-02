# pncp_mei_federal_pipeline.py
# Baixa CONTRATOS/EMPENHOS do PNCP (/api/consulta/v1/contratos) por data de publicação,
# filtra esfera FEDERAL (orgaoEntidade.esferaId = 'F'),
# normaliza CNPJ do fornecedor (tipoPessoa='PJ' e niFornecedor com 14 dígitos),
# cruza com sua tabela mei_ativo (já criada no DuckDB),
# e grava tabelas finais + alguns agregados (KPIs) no DuckDB.
#
# Requisitos:
#   pip install requests duckdb
#
# Uso:
#   python pncp_mei_federal_pipeline.py
#
# Observações:
# - O PNCP exige dataInicial/dataFinal no formato AAAAMMDD e pagina >= 1
# - tamanhoPagina <= 500 (use 500)
# - Se der 400 por tamanhoPagina, o script tenta fallback automaticamente

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

import duckdb
import requests
from project_paths import DB_PATH, PNCP_JSONL_PATH

# =========================
# CONFIG
# =========================
BASE_URL = "https://pncp.gov.br/api/consulta"
ENDPOINT = f"{BASE_URL}/v1/contratos"

# Janela (se quiser fixar, preencha START_YYYYMMDD/END_YYYYMMDD e deixe USE_DYNAMIC_RANGE=False)
USE_DYNAMIC_RANGE = True
DAYS_BACK = 184  # ~6 meses

START_YYYYMMDD = "20250714"
END_YYYYMMDD = "20260113"

# paginação
PAGE_SIZES = [500, 200, 100, 50, 20, 10]  # fallback se API reclamar do tamanho
SLEEP_BETWEEN_CALLS = 0.12

# saída
OUT_JSONL = PNCP_JSONL_PATH

# requests
TIMEOUT = 90
MAX_RETRIES = 6
RETRY_BACKOFF_BASE = 1.8  # exponencial

DIGITS_RE = re.compile(r"\D+")


# =========================
# HELPERS
# =========================
def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def get_range() -> tuple[str, str]:
    if not USE_DYNAMIC_RANGE:
        return START_YYYYMMDD, END_YYYYMMDD
    today = date.today()
    start = today - timedelta(days=DAYS_BACK)
    return yyyymmdd(start), yyyymmdd(today)


def only_digits(s: Optional[str]) -> str:
    return DIGITS_RE.sub("", s or "")


def safe_request(params: Dict[str, Any]) -> requests.Response:
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(ENDPOINT, params=params, headers={"accept": "*/*"}, timeout=TIMEOUT)
            return r
        except Exception as e:
            last_err = e
            sleep = (RETRY_BACKOFF_BASE ** (attempt - 1))
            print(f"[WARN] erro request (tentativa {attempt}/{MAX_RETRIES}): {e} -> aguardando {sleep:.1f}s")
            time.sleep(sleep)
    raise RuntimeError(f"Falha após {MAX_RETRIES} tentativas. Último erro: {last_err}")


def fetch_page(data_inicial: str, data_final: str, pagina: int, tamanho: int) -> Dict[str, Any]:
    params = {
        "dataInicial": data_inicial,
        "dataFinal": data_final,
        "pagina": pagina,
        "tamanhoPagina": tamanho,
    }
    r = safe_request(params)

    if r.status_code == 204:
        return {"_no_content": True}

    # Tratamento do 400
    if r.status_code == 400:
        try:
            err = r.json()
        except Exception:
            err = {"message": r.text}
        raise ValueError(err)

    r.raise_for_status()
    return r.json()


def extract_supplier_cnpj(item: Dict[str, Any]) -> Optional[str]:
    """
    Para /v1/contratos, o fornecedor vem claramente:
      - tipoPessoa: 'PJ' ou 'PF'
      - niFornecedor: CNPJ(14) ou CPF(11) ou outros
    """
    tipo = (item.get("tipoPessoa") or "").upper()
    ni = only_digits(str(item.get("niFornecedor") or ""))

    if tipo == "PJ" and len(ni) == 14:
        return ni
    return None


def ensure_dir(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)


# =========================
# ETAPA 1: DOWNLOAD PNCP -> JSONL
# =========================
def download_pncp_to_jsonl() -> int:
    data_inicial, data_final = get_range()
    print(f"PNCP /v1/contratos: {data_inicial} -> {data_final}")
    ensure_dir(OUT_JSONL)
    if OUT_JSONL.exists():
        OUT_JSONL.unlink()

    total = 0
    pagina = 1
    size_idx = 0

    with OUT_JSONL.open("w", encoding="utf-8") as f:
        while True:
            tamanho = PAGE_SIZES[size_idx]

            try:
                payload = fetch_page(data_inicial, data_final, pagina, tamanho)
            except ValueError as ve:
                # 400: tentar fallback de tamanhoPagina
                msg = str(ve).lower()
                if "tamanho de página inválido" in msg or "tamanho de pagina invalido" in msg:
                    if size_idx < len(PAGE_SIZES) - 1:
                        size_idx += 1
                        print(f"[WARN] 400 tamanhoPagina inválido. Tentando tamanhoPagina={PAGE_SIZES[size_idx]} ...")
                        continue
                raise

            if payload.get("_no_content"):
                print("204 No Content -> fim.")
                break

            data: List[Dict[str, Any]] = payload.get("data") or []
            if not data:
                print("Sem mais registros (data vazio). Encerrando.")
                break

            for item in data:
                item["_fornecedor_cnpj"] = extract_supplier_cnpj(item)
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

            total += len(data)
            print(
                f"pagina={pagina} tamanhoPagina={tamanho} lote={len(data)} total={total} "
                f"(totalPaginas={payload.get('totalPaginas')}, restantes={payload.get('paginasRestantes')})"
            )

            pagina += 1
            time.sleep(SLEEP_BETWEEN_CALLS)

    print(f"✅ Download concluído: {total} registros em {OUT_JSONL.resolve()}")
    return total


# =========================
# ETAPA 2: LOAD NO DUCKDB + FILTROS + JOIN MEI
# =========================
def load_and_build_tables():
    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA threads=8;")

    # 2.1 staging raw
    con.execute("DROP TABLE IF EXISTS pncp_contratos_raw;")
    con.execute(f"""
        CREATE TABLE pncp_contratos_raw AS
        SELECT * FROM read_json_auto('{str(OUT_JSONL).replace("'", "''")}');
    """)

    # 2.2 normalização de CNPJ fornecedor
    con.execute("ALTER TABLE pncp_contratos_raw ADD COLUMN IF NOT EXISTS fornecedor_cnpj VARCHAR;")
    con.execute("""
        UPDATE pncp_contratos_raw
        SET fornecedor_cnpj = _fornecedor_cnpj
        WHERE fornecedor_cnpj IS NULL;
    """)

    # 2.3 filtrar esfera federal
    # No schema do PNCP, esfera está em orgaoEntidade.esferaId (F/E/M/D).
    con.execute("DROP TABLE IF EXISTS pncp_contratos_federal_6m;")
    con.execute("""
        CREATE TABLE pncp_contratos_federal_6m AS
        SELECT *
        FROM pncp_contratos_raw
        WHERE orgaoEntidade.esferaId = 'F';
    """)

    # 2.4 cruzar com MEI ativo (já criado por você)
    con.execute("DROP TABLE IF EXISTS pncp_mei_federal_6m;")
    con.execute("""
        CREATE TABLE pncp_mei_federal_6m AS
        SELECT
            p.*,
            m.RAZAO_SOCIAL AS mei_razao_social,
            m.UF          AS mei_uf,
            m.MUNICIPIO   AS mei_municipio,
            m.CNAE_PRINCIPAL AS mei_cnae
        FROM pncp_contratos_federal_6m p
        JOIN mei_ativo m
          ON p.fornecedor_cnpj = m.CNPJ
        WHERE p.fornecedor_cnpj IS NOT NULL;
    """)

    # índices úteis
    con.execute("CREATE INDEX IF NOT EXISTS idx_pncp_fed_cnpj ON pncp_contratos_federal_6m(fornecedor_cnpj);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pncp_mei_fed_cnpj ON pncp_mei_federal_6m(fornecedor_cnpj);")

    # contagens
    cnt_raw = con.execute("SELECT COUNT(*) FROM pncp_contratos_raw").fetchone()[0]
    cnt_fed = con.execute("SELECT COUNT(*) FROM pncp_contratos_federal_6m").fetchone()[0]
    cnt_mei = con.execute("SELECT COUNT(*) FROM pncp_mei_federal_6m").fetchone()[0]

    print("\n=== COUNTS ===")
    print("pncp_contratos_raw:", cnt_raw)
    print("pncp_contratos_federal_6m:", cnt_fed)
    print("pncp_mei_federal_6m:", cnt_mei)

    # =========================
    # ETAPA 3: KPIs BASE (tabelas prontas p/ gráficos)
    # =========================

    # 3.1 KPI participação (volume e valor) - federal
    con.execute("DROP TABLE IF EXISTS kpi_mei_participacao_federal_6m;")
    con.execute("""
        CREATE TABLE kpi_mei_participacao_federal_6m AS
        WITH base AS (
            SELECT
                COUNT(*) AS contratos_total,
                SUM(COALESCE(valorGlobal, 0)) AS valor_total
            FROM pncp_contratos_federal_6m
        ),
        mei AS (
            SELECT
                COUNT(*) AS contratos_mei,
                SUM(COALESCE(valorGlobal, 0)) AS valor_mei
            FROM pncp_mei_federal_6m
        )
        SELECT
            mei.contratos_mei,
            base.contratos_total,
            CASE WHEN base.contratos_total = 0 THEN 0 ELSE (mei.contratos_mei::DOUBLE / base.contratos_total) END AS share_contratos,
            mei.valor_mei,
            base.valor_total,
            CASE WHEN base.valor_total = 0 THEN 0 ELSE (mei.valor_mei::DOUBLE / base.valor_total) END AS share_valor
        FROM base, mei;
    """)

    # 3.2 Top órgãos federais por valor MEI
    con.execute("DROP TABLE IF EXISTS kpi_mei_top_orgaos_federal_6m;")
    con.execute("""
        CREATE TABLE kpi_mei_top_orgaos_federal_6m AS
        SELECT
            orgaoEntidade.cnpj AS orgao_cnpj,
            orgaoEntidade.razaoSocial AS orgao_razao,
            COUNT(*) AS qtd_contratos,
            SUM(COALESCE(valorGlobal, 0)) AS valor_total
        FROM pncp_mei_federal_6m
        GROUP BY 1,2
        ORDER BY valor_total DESC
        LIMIT 50;
    """)

    # 3.3 Top UF do MEI vendedor (pela UF do MEI na RFB)
    con.execute("DROP TABLE IF EXISTS kpi_mei_top_uf_federal_6m;")
    con.execute("""
        CREATE TABLE kpi_mei_top_uf_federal_6m AS
        SELECT
            mei_uf AS uf,
            COUNT(*) AS qtd_contratos,
            SUM(COALESCE(valorGlobal, 0)) AS valor_total
        FROM pncp_mei_federal_6m
        GROUP BY 1
        ORDER BY valor_total DESC;
    """)

    # 3.4 Série temporal (dia) - MEI no federal
    con.execute("DROP TABLE IF EXISTS kpi_mei_serie_diaria_federal_6m;")
    con.execute("""
        CREATE TABLE kpi_mei_serie_diaria_federal_6m AS
        SELECT
            CAST(substr(CAST(dataPublicacaoPncp AS VARCHAR), 1, 10) AS DATE) AS dia,
            COUNT(*) AS qtd_contratos,
            SUM(COALESCE(valorGlobal, 0)) AS valor_total
        FROM pncp_mei_federal_6m
        GROUP BY 1
        ORDER BY 1;
    """)

    # 3.5 Top CNAE do MEI vendedor
    con.execute("DROP TABLE IF EXISTS kpi_mei_top_cnae_federal_6m;")
    con.execute("""
        CREATE TABLE kpi_mei_top_cnae_federal_6m AS
        SELECT
            mei_cnae AS cnae,
            COUNT(*) AS qtd_contratos,
            SUM(COALESCE(valorGlobal, 0)) AS valor_total
        FROM pncp_mei_federal_6m
        GROUP BY 1
        ORDER BY valor_total DESC
        LIMIT 50;
    """)

    # prints rápidos
    print("\n=== KPI participação (federal) ===")
    print(con.execute("SELECT * FROM kpi_mei_participacao_federal_6m").fetchdf())

    print("\n=== Top 10 UF MEI (valor) ===")
    print(con.execute("""
        SELECT * FROM kpi_mei_top_uf_federal_6m
        ORDER BY valor_total DESC
        LIMIT 10
    """).fetchdf())

    con.close()
    print("\n✅ OK - tabelas PNCP + MEI + KPIs gravadas no DuckDB")


def main():
    total = download_pncp_to_jsonl()
    if total == 0:
        print("Nada baixado. Encerrando.")
        return
    load_and_build_tables()


if __name__ == "__main__":
    main()
