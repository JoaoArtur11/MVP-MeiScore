import csv
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import requests


URL = 'https://pncp.gov.br/api/consulta/v1/contratos'
OUT_DIR = Path(os.environ.get('MVP_SAMPLE_DIR', 'amostra_dados'))
DATA_FINAL = os.environ.get('MVP_SAMPLE_DATA_FINAL', date.today().strftime('%Y%m%d'))
DATA_INICIAL = os.environ.get(
    'MVP_SAMPLE_DATA_INICIAL',
    (date.today() - timedelta(days=int(os.environ.get('MVP_SAMPLE_DAYS_BACK', '30')))).strftime('%Y%m%d'),
)
PAGE_SIZE = int(os.environ.get('MVP_SAMPLE_PAGE_SIZE', '50'))
MAX_ROWS = int(os.environ.get('MVP_SAMPLE_MAX_ROWS', '300'))
SLEEP_SECONDS = float(os.environ.get('MVP_SAMPLE_SLEEP_SECONDS', '0.1'))

PNCP_FIELDS = [
    'numeroControlePncpCompra',
    'numeroContratoEmpenho',
    'dataPublicacaoPncp',
    'dataAssinatura',
    'tipoPessoa',
    'niFornecedor',
    'nomeRazaoSocialFornecedor',
    'valorGlobal',
    'orgaoEntidade_razaoSocial',
    'orgaoEntidade_cnpj',
    'orgaoEntidade_esferaId',
]

CNAES_DEMO = [
    '9001902', '4520005', '7729202', '4321500', '7319002',
    '8230001', '4399103', '7420001', '5611203', '9511800',
]
UFS_DEMO = ['SP', 'SC', 'GO', 'BA', 'PR', 'MG', 'RS', 'CE', 'PA', 'MT']
UFS_POR_CONTRATO_DEMO = max(1, int(os.environ.get('MVP_SAMPLE_UF_REPEAT', '5')))


def digits_only(value: object) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def fetch_page(session: requests.Session, pagina: int) -> dict:
    params = {
        'dataInicial': DATA_INICIAL,
        'dataFinal': DATA_FINAL,
        'pagina': pagina,
        'tamanhoPagina': PAGE_SIZE,
    }
    for attempt in range(1, 6):
        try:
            response = session.get(URL, params=params, timeout=90)
            if response.status_code == 204:
                return {'data': [], 'totalPaginas': pagina}
            if response.status_code >= 500:
                raise RuntimeError(f'status {response.status_code}')
            return response.json()
        except Exception as exc:
            wait = min(attempt * 2, 20)
            print(f'[WARN] PNCP pagina {pagina} tentativa {attempt}: {exc}; aguardando {wait}s')
            time.sleep(wait)
    raise RuntimeError(f'Falha ao baixar pagina {pagina} do PNCP')


def normalize_pncp_item(item: dict) -> dict:
    org = item.get('orgaoEntidade') or {}
    return {
        'numeroControlePncpCompra': item.get('numeroControlePncpCompra'),
        'numeroContratoEmpenho': item.get('numeroContratoEmpenho'),
        'dataPublicacaoPncp': item.get('dataPublicacaoPncp'),
        'dataAssinatura': item.get('dataAssinatura'),
        'tipoPessoa': item.get('tipoPessoa'),
        'niFornecedor': digits_only(item.get('niFornecedor')).zfill(14),
        'nomeRazaoSocialFornecedor': item.get('nomeRazaoSocialFornecedor'),
        'valorGlobal': item.get('valorGlobal'),
        'orgaoEntidade_razaoSocial': org.get('razaoSocial'),
        'orgaoEntidade_cnpj': org.get('cnpj'),
        'orgaoEntidade_esferaId': org.get('esferaId'),
    }


def baixar_pncp_amostra() -> list[dict]:
    session = requests.Session()
    session.headers.update({'accept': '*/*', 'user-agent': 'mvp-score-mei-sample/1.0'})

    rows: list[dict] = []
    pagina = 1
    total_paginas = None

    while len(rows) < MAX_ROWS:
        payload = fetch_page(session, pagina)
        total_paginas = int(payload.get('totalPaginas') or total_paginas or pagina)
        data = payload.get('data') or []
        if not data:
            break

        for item in data:
            row = normalize_pncp_item(item)
            if row['tipoPessoa'] == 'PJ' and len(row['niFornecedor']) == 14:
                rows.append(row)
                if len(rows) >= MAX_ROWS:
                    break

        print(f'PNCP pagina={pagina}/{total_paginas} linhas_pj={len(rows)}')
        if pagina >= total_paginas:
            break
        pagina += 1
        if SLEEP_SECONDS:
            time.sleep(SLEEP_SECONDS)

    if not rows:
        raise RuntimeError('Nenhum contrato PJ foi encontrado para a janela de amostra.')
    return rows


def escrever_pncp(rows: list[dict]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / 'pncp_contratos_raw.csv'
    with out_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=PNCP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def escrever_fixture_rfb(rows: list[dict]) -> dict:
    # A Receita Federal publica apenas ZIPs grandes. Este fixture minimo preserva
    # o layout usado pelo pipeline para permitir smoke test pequeno no GitHub.
    snapshot = 'demo-sintetico'
    out_dir = OUT_DIR / 'rf_cnpj_csv' / '_extracted' / snapshot
    out_dir.mkdir(parents=True, exist_ok=True)

    cnpjs = []
    seen = set()
    for row in rows:
        cnpj = digits_only(row['niFornecedor']).zfill(14)
        if len(cnpj) == 14 and cnpj not in seen:
            seen.add(cnpj)
            cnpjs.append(cnpj)

    empresas_path = out_dir / 'K0000.K03200Y0.DEMO.EMPRECSV'
    estabele_path = out_dir / 'K0000.K03200Y0.DEMO.ESTABELE'
    simples_path = out_dir / 'F.K03200W.SIMPLES.DEMO'

    with empresas_path.open('w', newline='', encoding='latin1') as f_emp, \
            estabele_path.open('w', newline='', encoding='latin1') as f_est, \
            simples_path.open('w', newline='', encoding='latin1') as f_sim:
        emp_writer = csv.writer(f_emp, delimiter=';')
        est_writer = csv.writer(f_est, delimiter=';')
        sim_writer = csv.writer(f_sim, delimiter=';')

        for idx, cnpj in enumerate(cnpjs):
            basico, ordem, dv = cnpj[:8], cnpj[8:12], cnpj[12:14]
            uf = UFS_DEMO[(idx // UFS_POR_CONTRATO_DEMO) % len(UFS_DEMO)]
            cnae_shift = (idx // (UFS_POR_CONTRATO_DEMO * len(UFS_DEMO))) % len(CNAES_DEMO)
            cnae = CNAES_DEMO[(idx + cnae_shift) % len(CNAES_DEMO)]

            emp_writer.writerow([basico, f'MEI DEMO {idx + 1}', '', '', '', '', ''])

            est = [''] * 30
            est[0] = basico
            est[1] = ordem
            est[2] = dv
            est[5] = '02'
            est[11] = cnae
            est[19] = uf
            est_writer.writerow(est)

            sim_writer.writerow([basico, '', '', '', 'S', '', ''])

    return {
        'snapshot': snapshot,
        'empresas': str(empresas_path),
        'estabelecimentos': str(estabele_path),
        'simples': str(simples_path),
        'cnpjs_fixture': len(cnpjs),
        'ufs_demo': UFS_DEMO,
        'cnaes_demo': CNAES_DEMO,
        'observacao_distribuicao': (
            'O fixture distribui CNPJs em ciclos de UF e CNAE para gerar mais '
            'combinacoes CNAE x UF no dashboard de demonstracao.'
        ),
        'observacao': (
            'PNCP real baixado da API oficial; fixture RFB sintetico no layout '
            'Receita porque a fonte oficial so publica arquivos completos grandes.'
        ),
    }


def main():
    rows = baixar_pncp_amostra()
    pncp_path = escrever_pncp(rows)
    rfb_meta = escrever_fixture_rfb(rows)

    meta = {
        'pncp_api': URL,
        'data_inicial': DATA_INICIAL,
        'data_final': DATA_FINAL,
        'page_size': PAGE_SIZE,
        'max_rows': MAX_ROWS,
        'pncp_csv': str(pncp_path),
        'pncp_rows': len(rows),
        'rfb_fixture': rfb_meta,
        'uso': [
            "$env:MVP_BASE_DIR='amostra_dados'",
            'python mvp_score/fase1_preparacao.py',
            'python mvp_score/fase2_features.py',
            'python mvp_score/fase3_modelos.py',
            'python mvp_score/fase4_visualizacoes.py',
        ],
    }
    meta_path = OUT_DIR / 'metadata_amostra.json'
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'Amostra PNCP: {pncp_path} ({len(rows)} linhas)')
    print(f'Fixture RFB: {OUT_DIR / "rf_cnpj_csv" / "_extracted" / rfb_meta["snapshot"]}')
    print(f'Metadados: {meta_path}')


if __name__ == '__main__':
    main()
