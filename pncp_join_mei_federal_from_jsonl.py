# pncp_join_mei_federal_from_jsonl.py
# Usa o pncp_contratos_6m.jsonl ja baixado, carrega no DuckDB,
# filtra esfera federal (esferaId='F'),
# normaliza CNPJ do fornecedor (tipoPessoa='PJ' e niFornecedor 14 digitos),
# cruza com mei_ativo, e cria KPIs.

import duckdb

from project_paths import DB_PATH, PNCP_JSONL_PATH


def main():
    if not PNCP_JSONL_PATH.exists():
        raise FileNotFoundError(f"Nao achei o JSONL em: {PNCP_JSONL_PATH}")

    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA threads=8;")

    con.execute("DROP TABLE IF EXISTS pncp_contratos_raw;")
    con.execute(
        f"""
        CREATE TABLE pncp_contratos_raw AS
        SELECT * FROM read_json_auto('{str(PNCP_JSONL_PATH).replace("'", "''")}');
    """
    )

    con.execute("ALTER TABLE pncp_contratos_raw ADD COLUMN IF NOT EXISTS fornecedor_cnpj VARCHAR;")
    con.execute(
        """
        UPDATE pncp_contratos_raw
        SET fornecedor_cnpj =
            CASE
                WHEN upper(tipoPessoa) = 'PJ'
                     AND length(regexp_replace(COALESCE(niFornecedor,''), '[^0-9]', '', 'g')) = 14
                THEN regexp_replace(COALESCE(niFornecedor,''), '[^0-9]', '', 'g')
                ELSE NULL
            END;
    """
    )

    con.execute("DROP TABLE IF EXISTS pncp_contratos_federal_6m;")
    con.execute(
        """
        CREATE TABLE pncp_contratos_federal_6m AS
        SELECT *
        FROM pncp_contratos_raw
        WHERE orgaoEntidade.esferaId = 'F';
    """
    )

    con.execute("DROP TABLE IF EXISTS pncp_mei_federal_6m;")
    con.execute(
        """
        CREATE TABLE pncp_mei_federal_6m AS
        SELECT
            p.*,
            m.RAZAO_SOCIAL AS mei_razao_social,
            m.UF AS mei_uf,
            m.MUNICIPIO AS mei_municipio,
            m.CNAE_PRINCIPAL AS mei_cnae
        FROM pncp_contratos_federal_6m p
        JOIN mei_ativo m
          ON p.fornecedor_cnpj = m.CNPJ
        WHERE p.fornecedor_cnpj IS NOT NULL;
    """
    )

    con.execute("CREATE INDEX IF NOT EXISTS idx_pncp_raw_cnpj ON pncp_contratos_raw(fornecedor_cnpj);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pncp_fed_cnpj ON pncp_contratos_federal_6m(fornecedor_cnpj);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pncp_mei_fed_cnpj ON pncp_mei_federal_6m(fornecedor_cnpj);")

    con.execute("DROP TABLE IF EXISTS kpi_mei_participacao_federal_6m;")
    con.execute(
        """
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
    """
    )

    con.execute("DROP TABLE IF EXISTS kpi_mei_top_orgaos_federal_6m;")
    con.execute(
        """
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
    """
    )

    con.execute("DROP TABLE IF EXISTS kpi_mei_top_uf_federal_6m;")
    con.execute(
        """
        CREATE TABLE kpi_mei_top_uf_federal_6m AS
        SELECT
            mei_uf AS uf,
            COUNT(*) AS qtd_contratos,
            SUM(COALESCE(valorGlobal, 0)) AS valor_total
        FROM pncp_mei_federal_6m
        GROUP BY 1
        ORDER BY valor_total DESC;
    """
    )

    con.execute("DROP TABLE IF EXISTS kpi_mei_serie_diaria_federal_6m;")
    con.execute(
        """
        CREATE TABLE kpi_mei_serie_diaria_federal_6m AS
        SELECT
            CAST(substr(CAST(dataPublicacaoPncp AS VARCHAR), 1, 10) AS DATE) AS dia,
            COUNT(*) AS qtd_contratos,
            SUM(COALESCE(valorGlobal, 0)) AS valor_total
        FROM pncp_mei_federal_6m
        GROUP BY 1
        ORDER BY 1;
    """
    )

    con.execute("DROP TABLE IF EXISTS kpi_mei_top_cnae_federal_6m;")
    con.execute(
        """
        CREATE TABLE kpi_mei_top_cnae_federal_6m AS
        SELECT
            mei_cnae AS cnae,
            COUNT(*) AS qtd_contratos,
            SUM(COALESCE(valorGlobal, 0)) AS valor_total
        FROM pncp_mei_federal_6m
        GROUP BY 1
        ORDER BY valor_total DESC
        LIMIT 50;
    """
    )

    cnt_raw = con.execute("SELECT COUNT(*) FROM pncp_contratos_raw").fetchone()[0]
    cnt_fed = con.execute("SELECT COUNT(*) FROM pncp_contratos_federal_6m").fetchone()[0]
    cnt_mei = con.execute("SELECT COUNT(*) FROM pncp_mei_federal_6m").fetchone()[0]

    print("\n=== COUNTS ===")
    print("pncp_contratos_raw:", cnt_raw)
    print("pncp_contratos_federal_6m:", cnt_fed)
    print("pncp_mei_federal_6m:", cnt_mei)

    print("\n=== KPI participacao (federal) ===")
    print(con.execute("SELECT * FROM kpi_mei_participacao_federal_6m").fetchdf())

    con.close()
    print("\nOK - Cruzamento concluido e KPIs gerados no DuckDB")


if __name__ == "__main__":
    main()
