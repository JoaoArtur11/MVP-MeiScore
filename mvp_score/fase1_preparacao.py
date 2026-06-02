import os
import glob
import csv
import re
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

MVP_MEI_MAX_EMP_FILES = int(os.environ.get('MVP_MEI_MAX_EMP_FILES', '10'))
MVP_MEI_MAX_EST_FILES = int(os.environ.get('MVP_MEI_MAX_EST_FILES', '10'))
MVP_MEI_MAX_SIMPLES_FILES = int(os.environ.get('MVP_MEI_MAX_SIMPLES_FILES', '1'))
CHUNK_SIZE = int(os.environ.get('MVP_RFB_CHUNK_SIZE', '200000'))


# =========================
# Descobertas da inspeção (Passo 0 obrigatório)
# =========================
# 1) O passo 0 foi executado e salvo em mvp_score/inspecao_passo0.txt
# 2) Foram encontrados CSVs em out_charts/, mas eles são agregados (KPIs), não base transacional PNCP.
# 3) A base MEI (RFB) está em arquivos delimitados por ';' sem extensão .csv,
#    com nomes como:
#      - K3241...EMPRECSV (empresas)
#      - K3241...ESTABELE (estabelecimentos)
#      - F.K03200$W.SIMPLES... (simples/MEI)
# 4) Amostras inspecionadas mostram:
#    - EMPRECSV: 7 colunas, sem header
#    - ESTABELE: 30 colunas, sem header
#    - SIMPLES: 7 colunas, sem header
# 5) CSV PNCP bruto foi criado em pncp_contratos_raw.csv com colunas:
#    niFornecedor, tipoPessoa, valorGlobal, dataPublicacaoPncp, orgaoEntidade_razaoSocial.


def run_passo0_inspecao(output_path: Path, scan_dir: Path = Path('.')) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []

    for root, dirs, files in os.walk(scan_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', 'env', '__pycache__', 'node_modules')]
        for file in files:
            filepath = os.path.join(root, file)
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            lines.append(f"{filepath}  ({size_mb:.1f} MB)")

    for csv_path in glob.glob(str(scan_dir / '**' / '*.csv'), recursive=True):
        try:
            df = pd.read_csv(csv_path, nrows=3, sep=None, engine='python', encoding='utf-8')
            enc_used = 'utf-8'
        except Exception:
            try:
                df = pd.read_csv(csv_path, nrows=3, sep=None, engine='python', encoding='latin1')
                enc_used = 'latin1'
            except Exception as e:
                lines.append(f"ERRO ao ler {csv_path}: {e}")
                continue

        lines.append(f"\n--- {csv_path} ---")
        lines.append(f"Encoding detectado: {enc_used}")
        lines.append(f"Colunas: {list(df.columns)}")
        lines.append(df.head(3).to_string(index=False))

    output_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"Passo 0 executado. Saída completa em: {output_path}")


def detect_sep_encoding(file_path: Path) -> tuple[str, str]:
    for enc in ('utf-8', 'latin1'):
        try:
            with open(file_path, 'r', encoding=enc) as f:
                sample = f.read(20000)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=';,|\t')
                sep = dialect.delimiter
            except Exception:
                sep = ';'
            return sep, enc
        except Exception:
            continue
    raise RuntimeError(f"Não foi possível detectar encoding/separador para {file_path}")


def digits_only(val: object) -> str:
    if pd.isna(val):
        return ''
    return re.sub(r'\D+', '', str(val))


def normalize_cnpj_series(s: pd.Series) -> pd.Series:
    return s.astype(str).map(digits_only).str.zfill(14)


def discover_mei_files(base_dir: Path) -> dict:
    extracted_dir = base_dir / 'rf_cnpj_csv' / '_extracted'
    search_root = extracted_dir if extracted_dir.exists() else base_dir
    all_files = [
        p for p in search_root.rglob('*')
        if p.is_file() and p.suffix.lower() != '.manifest' and not p.name.startswith('.')
    ]

    empresas = [p for p in all_files if 'EMPRECSV' in p.name.upper()]
    estabele = [p for p in all_files if 'ESTABELE' in p.name.upper()]
    simples = [p for p in all_files if 'SIMPLES' in p.name.upper()]

    if not empresas or not estabele or not simples:
        raise FileNotFoundError('Arquivos MEI (EMPRECSV/ESTABELE/SIMPLES) não encontrados na pasta do projeto.')

    def latest_date_key(path: Path) -> str:
        m = re.findall(r'\d{4}-\d{2}-\d{2}', str(path))
        return m[-1] if m else ''

    latest = max([latest_date_key(p) for p in empresas + estabele + simples])

    empresas = sorted([p for p in empresas if latest in str(p)] or empresas)[:MVP_MEI_MAX_EMP_FILES]
    estabele = sorted([p for p in estabele if latest in str(p)] or estabele)[:MVP_MEI_MAX_EST_FILES]
    simples = sorted([p for p in simples if latest in str(p)] or simples)[:MVP_MEI_MAX_SIMPLES_FILES]

    return {'snapshot': latest, 'empresas': empresas, 'estabelecimentos': estabele, 'simples': simples}


def pick_pncp_contract_file(base_dir: Path) -> tuple[Path, dict, str, str]:
    candidates = [
        p for p in base_dir.rglob('*.csv')
        if 'out_charts' not in str(p).lower() and 'mvp_score' not in str(p).lower()
    ]

    for p in sorted(candidates):
        try:
            sep, enc = detect_sep_encoding(p)
            df = pd.read_csv(p, nrows=5, sep=sep, encoding=enc)
        except Exception:
            continue

        cols = {c.lower().strip(): c for c in df.columns}
        keyset = set(cols.keys())

        has_cnpj = any(k in keyset for k in ['nifornecedor', 'cnpj_fornecedor', 'cnpjfornecedor'])
        has_tipo = any('tipopessoa' == k or 'tipo_pessoa' == k for k in keyset)
        has_valor = any(k in keyset for k in ['valorglobal', 'valor_global', 'valorcontrato', 'valor_contrato'])
        has_data = any('data' in k for k in keyset)
        has_orgao = any('orgao' in k for k in keyset)

        if has_cnpj and has_tipo and has_valor and has_data and has_orgao:
            return p, cols, sep, enc

    raise FileNotFoundError(
        'Nenhum CSV bruto PNCP de contratos foi identificado automaticamente. '
        'A inspeção encontrou apenas CSVs agregados em out_charts/. '
        'Inclua um CSV de contratos PNCP com colunas equivalentes a niFornecedor, tipoPessoa, valorGlobal, dataPublicacao e órgão.'
    )


def _read_filtered_chunks(file_paths: list[Path], usecols: list[int], sep: str, encoding: str, basicos_set: set[str]) -> pd.DataFrame:
    def _manual_parse_file(fp: Path, usecols_local: list[int], basicos_local: set[str], sep_local: str) -> pd.DataFrame:
        max_idx = max(usecols_local)
        out_rows = []
        sep_b = sep_local.encode('latin1', errors='ignore') if sep_local else b';'
        if not sep_b:
            sep_b = b';'

        with fp.open('rb') as fh:
            for raw_line in fh:
                if not raw_line:
                    continue
                raw_line = raw_line.replace(b'\x00', b'').strip()
                if not raw_line:
                    continue

                parts = raw_line.split(sep_b)
                if len(parts) <= max_idx:
                    continue

                cnpj_basico = parts[0].decode('latin1', errors='ignore').strip().strip('"').zfill(8)
                if cnpj_basico not in basicos_local:
                    continue

                row = {}
                for idx in usecols_local:
                    val = parts[idx].decode('latin1', errors='ignore').strip().strip('"') if idx < len(parts) else ''
                    row[idx] = val
                row[usecols_local[0]] = cnpj_basico
                out_rows.append(row)

        if not out_rows:
            return pd.DataFrame(columns=usecols_local)
        return pd.DataFrame(out_rows, columns=usecols_local)

    parts = []
    for fp in file_paths:
        print(f'  lendo {fp.name} ...')
        tried = []
        ok = False
        for enc_try in [encoding, 'latin1', 'utf-8', 'utf-16']:
            if enc_try in tried:
                continue
            tried.append(enc_try)
            try:
                for chunk in pd.read_csv(
                    fp,
                    sep=sep,
                    header=None,
                    usecols=usecols,
                    dtype=str,
                    encoding=enc_try,
                    engine='python',
                    chunksize=CHUNK_SIZE,
                    on_bad_lines='skip',
                ):
                    chunk = chunk.fillna('')
                    cnpj_basico = chunk.iloc[:, 0].astype(str).str.strip().str.zfill(8)
                    m = cnpj_basico.isin(basicos_set)
                    if m.any():
                        sub = chunk.loc[m].copy()
                        sub.iloc[:, 0] = cnpj_basico.loc[m]
                        parts.append(sub)
                ok = True
                break
            except (UnicodeError, csv.Error):
                continue
        if not ok:
            print(f'[WARN] pandas falhou para {fp.name}; ativando parser manual. Encodings testados: {tried}')
            manual_df = _manual_parse_file(fp, usecols, basicos_set, sep)
            if not manual_df.empty:
                parts.append(manual_df)
            else:
                print(f'[WARN] parser manual sem linhas aproveitáveis: {fp.name}')
    if not parts:
        return pd.DataFrame(columns=usecols)
    return pd.concat(parts, ignore_index=True)


def build_mei_ativo_pandas(mei_files: dict, pncp_basicos: list[str]) -> pd.DataFrame:
    basicos_set = set(pd.Series(pncp_basicos, dtype=str).str.zfill(8).tolist())

    emp_sep, emp_enc = detect_sep_encoding(mei_files['empresas'][0])
    est_sep, est_enc = detect_sep_encoding(mei_files['estabelecimentos'][0])
    sim_sep, sim_enc = detect_sep_encoding(mei_files['simples'][0])

    emp = _read_filtered_chunks(mei_files['empresas'], [0, 1], emp_sep, emp_enc, basicos_set)
    est = _read_filtered_chunks(mei_files['estabelecimentos'], [0, 1, 2, 5, 11, 19], est_sep, est_enc, basicos_set)
    sim = _read_filtered_chunks(mei_files['simples'], [0, 4], sim_sep, sim_enc, basicos_set)

    if emp.empty or est.empty or sim.empty:
        return pd.DataFrame(columns=['cnpj', 'cnpj_basico', 'uf', 'cnae_principal', 'situacao_cadastral', 'flag_mei'])

    emp.columns = ['cnpj_basico', 'razao_social']
    est.columns = ['cnpj_basico', 'cnpj_ordem', 'cnpj_dv', 'situacao_cadastral', 'cnae_principal', 'uf']
    sim.columns = ['cnpj_basico', 'flag_mei']

    emp['cnpj_basico'] = emp['cnpj_basico'].astype(str).str.zfill(8)
    est['cnpj_basico'] = est['cnpj_basico'].astype(str).str.zfill(8)
    sim['cnpj_basico'] = sim['cnpj_basico'].astype(str).str.zfill(8)

    est['cnpj_ordem'] = est['cnpj_ordem'].astype(str).str.zfill(4)
    est['cnpj_dv'] = est['cnpj_dv'].astype(str).str.zfill(2)
    est['situacao_cadastral'] = est['situacao_cadastral'].astype(str).str.strip()
    sim['flag_mei'] = sim['flag_mei'].astype(str).str.upper().str.strip()

    mei = (
        est.merge(emp[['cnpj_basico', 'razao_social']], on='cnpj_basico', how='inner')
        .merge(sim[['cnpj_basico', 'flag_mei']], on='cnpj_basico', how='inner')
    )

    sit = mei['situacao_cadastral'].astype(str).str.strip().str.lstrip('0')
    mei = mei[(mei['flag_mei'] == 'S') & (sit == '2')].copy()
    mei['cnpj'] = mei['cnpj_basico'] + mei['cnpj_ordem'] + mei['cnpj_dv']

    return mei[['cnpj', 'cnpj_basico', 'uf', 'cnae_principal', 'situacao_cadastral', 'flag_mei']].drop_duplicates()


def phase1_main():
    base_dir = Path(os.environ.get('MVP_BASE_DIR', '.'))
    os.makedirs('mvp_score', exist_ok=True)
    os.makedirs('mvp_score/dados', exist_ok=True)
    os.makedirs('mvp_score/resultados', exist_ok=True)

    run_passo0_inspecao(Path('mvp_score/inspecao_passo0.txt'), base_dir)

    mei_files = discover_mei_files(base_dir)
    print(f"Snapshot MEI identificado: {mei_files['snapshot']}")
    print(f"EMPRESAS arquivos: {len(mei_files['empresas'])}")
    print(f"ESTABELECIMENTOS arquivos: {len(mei_files['estabelecimentos'])}")
    print(f"SIMPLES arquivos: {len(mei_files['simples'])}")

    pncp_file, pncp_cols, pncp_sep, pncp_enc = pick_pncp_contract_file(base_dir)
    print(f"Arquivo PNCP identificado: {pncp_file}")
    print(f"Separador PNCP: {pncp_sep} | Encoding PNCP: {pncp_enc}")
    print(f"Colunas PNCP (amostra): {list(pncp_cols.values())}")

    col_lower = {k.lower().strip(): v for k, v in pncp_cols.items()}

    cnpj_col = col_lower.get('nifornecedor') or col_lower.get('cnpjfornecedor') or col_lower.get('cnpj_fornecedor')
    tipo_col = col_lower.get('tipopessoa') or col_lower.get('tipo_pessoa')
    valor_col = col_lower.get('valorglobal') or col_lower.get('valor_global') or col_lower.get('valorcontrato') or col_lower.get('valor_contrato')

    data_col = None
    for c in pncp_cols.values():
        cl = c.lower()
        if 'data' in cl and ('public' in cl or 'contrat' in cl or 'assin' in cl):
            data_col = c
            break
    if data_col is None:
        for c in pncp_cols.values():
            if 'data' in c.lower():
                data_col = c
                break

    orgao_col = None
    for c in pncp_cols.values():
        if 'orgao' in c.lower():
            orgao_col = c
            break

    required = [cnpj_col, tipo_col, valor_col, data_col, orgao_col]
    if any(v is None for v in required):
        raise RuntimeError(
            f"Não foi possível mapear todas as colunas PNCP necessárias. Mapeamento atual: "
            f"cnpj={cnpj_col}, tipo={tipo_col}, valor={valor_col}, data={data_col}, orgao={orgao_col}"
        )

    pncp_df = pd.read_csv(pncp_file, sep=pncp_sep, encoding=pncp_enc, low_memory=False)
    total_pncp = len(pncp_df)

    pncp_df[tipo_col] = pncp_df[tipo_col].astype(str).str.upper().str.strip()
    pncp_pj = pncp_df[pncp_df[tipo_col] == 'PJ'].copy()
    total_pncp_pj = len(pncp_pj)

    pncp_pj['cnpj'] = normalize_cnpj_series(pncp_pj[cnpj_col])

    pncp_pj[valor_col] = (
        pncp_pj[valor_col]
        .astype(str)
        .str.replace('.', '', regex=False)
        .str.replace(',', '.', regex=False)
    )
    pncp_pj[valor_col] = pd.to_numeric(pncp_pj[valor_col], errors='coerce').fillna(0.0)
    pncp_pj['orgao_resumido'] = pncp_pj[orgao_col].astype(str).str.strip()

    pncp_basicos = pncp_pj['cnpj'].astype(str).str.slice(0, 8).dropna().unique().tolist()
    mei_df = build_mei_ativo_pandas(mei_files, pncp_basicos)

    joined = pncp_pj.merge(mei_df, on='cnpj', how='inner')

    total_join = len(joined)
    taxa_match = (total_join / total_pncp_pj) if total_pncp_pj else 0.0

    print(f"Total contratos PNCP: {total_pncp}")
    print(f"Total após filtro PJ: {total_pncp_pj}")
    print(f"Total após join com MEI ativo: {total_join}")
    print(f"Taxa de match: {taxa_match:.4%}")

    if total_join < 100:
        print('ALERTA: join com menos de 100 registros. Verifique formatação de CNPJ e schema PNCP.')

    con = duckdb.connect(':memory:')
    con.register('joined_df', joined)
    tabela = con.execute(f"""
        SELECT
            cnae_principal AS CNAE,
            uf AS UF,
            COUNT(*) AS count_contratos,
            SUM({valor_col}) AS valor_total,
            AVG({valor_col}) AS valor_medio,
            COUNT(DISTINCT orgao_resumido) AS n_orgaos,
            COUNT(DISTINCT cnpj) AS n_meis
        FROM joined_df
        GROUP BY 1,2
    """).fetch_df()

    out_path = Path('mvp_score/dados/tabela_cnae_uf.csv')
    tabela.to_csv(out_path, index=False, encoding='utf-8')

    print(f"Shape tabela_cnae_uf: {tabela.shape}")
    print(tabela.head(10))
    print(tabela.describe(include='all'))

    metadata = {
        'pncp_file': str(pncp_file),
        'pncp_sep': pncp_sep,
        'pncp_encoding': pncp_enc,
        'pncp_columns': {
            'cnpj': cnpj_col,
            'tipo_pessoa': tipo_col,
            'valor': valor_col,
            'data': data_col,
            'orgao': orgao_col,
        },
        'mei_snapshot': mei_files['snapshot'],
        'totais': {
            'pncp_total': int(total_pncp),
            'pncp_pj': int(total_pncp_pj),
            'join_mei': int(total_join),
            'taxa_match': float(taxa_match),
        },
    }
    Path('mvp_score/dados/metadata_fase1.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')

    print('OK - Fase 1 concluida com sucesso.')


if __name__ == '__main__':
    phase1_main()
