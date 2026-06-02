import csv
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import requests

URL = 'https://pncp.gov.br/api/consulta/v1/contratos'
DAYS_BACK = int(os.environ.get('PNCP_DAYS_BACK', '184'))
PAGE_SIZE = int(os.environ.get('PNCP_PAGE_SIZE', '500'))
SLEEP_BETWEEN = float(os.environ.get('PNCP_SLEEP_SECONDS', '0.02'))
PAGE_BATCH = int(os.environ.get('PNCP_PAGE_BATCH', '250'))  # paginas por execucao no modo sequencial
RESUME = os.environ.get('PNCP_RESUME', '1') == '1'
STRICT_RESUME = os.environ.get('PNCP_STRICT_RESUME', '1') == '1'
CONTINUE_ON_PAGE_ERROR = os.environ.get('PNCP_CONTINUE_ON_PAGE_ERROR', '1') == '1'
MAX_RETRIES = int(os.environ.get('PNCP_MAX_RETRIES', '6'))
RETRY_FOREVER = os.environ.get('PNCP_RETRY_FOREVER', '0') == '1'
RETRY_BACKOFF_MAX = int(os.environ.get('PNCP_RETRY_BACKOFF_MAX', '60'))
FIXED_DATA_INICIAL = os.environ.get('PNCP_DATA_INICIAL', '').strip()
FIXED_DATA_FINAL = os.environ.get('PNCP_DATA_FINAL', '').strip()

# Modo paralelo por faixa (se ambos definidos)
PAGE_START_RAW = os.environ.get('PNCP_PAGE_START', '').strip()
PAGE_END_RAW = os.environ.get('PNCP_PAGE_END', '').strip()
RANGE_MODE = bool(PAGE_START_RAW and PAGE_END_RAW)

OUT = Path(os.environ.get('PNCP_OUT_CSV', 'pncp_contratos_raw.csv'))
STATE_PATH = Path(os.environ.get('PNCP_STATE_JSON', 'mvp_score/resultados/pncp_download_state.json'))
VALIDATION_OUT = Path(os.environ.get('PNCP_VALIDATION_JSON', 'mvp_score/resultados/pncp_download_validation.json'))

FIELDS = [
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


def fetch_page(session: requests.Session, data_inicial: str, data_final: str, pagina: int, tamanho_pagina: int) -> dict:
    params = {
        'dataInicial': data_inicial,
        'dataFinal': data_final,
        'pagina': pagina,
        'tamanhoPagina': tamanho_pagina,
    }
    payload = None
    attempt = 0
    while True:
        attempt += 1
        try:
            r = session.get(URL, params=params, timeout=120)
            if r.status_code == 204:
                return {'data': []}
            if r.status_code >= 500:
                raise RuntimeError(f'status {r.status_code}')
            payload = r.json()
            break
        except Exception as e:
            wait = min(attempt * 2, RETRY_BACKOFF_MAX)
            print(f'[WARN] pagina {pagina} tentativa {attempt} falhou: {e} (wait {wait}s)')
            time.sleep(wait)
            if (not RETRY_FOREVER) and attempt >= MAX_RETRIES:
                break

    if payload is None:
        raise RuntimeError(f'Falha definitiva ao baixar pagina {pagina}')
    return payload


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def write_failed_pages_csv(path: Path, failed_pages: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['pagina', 'erro'])
        w.writeheader()
        for item in failed_pages:
            w.writerow({'pagina': item.get('pagina'), 'erro': item.get('erro')})


def resolve_window(state: dict | None) -> tuple[str, str]:
    # 1) Se usuário fixou por env, usa env.
    # 2) Senão, se há state de resume, preserva janela do state.
    # 3) Senão, usa janela dinâmica (hoje - DAYS_BACK).
    if FIXED_DATA_INICIAL and FIXED_DATA_FINAL:
        return FIXED_DATA_INICIAL, FIXED_DATA_FINAL
    if state is not None:
        return state.get('data_inicial'), state.get('data_final')

    end = date.today()
    start = end - timedelta(days=DAYS_BACK)
    return start.strftime('%Y%m%d'), end.strftime('%Y%m%d')


def write_rows_for_page(writer: csv.DictWriter, data: list[dict]) -> int:
    wrote = 0
    for it in data:
        org = it.get('orgaoEntidade') or {}
        writer.writerow({
            'numeroControlePncpCompra': it.get('numeroControlePncpCompra'),
            'numeroContratoEmpenho': it.get('numeroContratoEmpenho'),
            'dataPublicacaoPncp': it.get('dataPublicacaoPncp'),
            'dataAssinatura': it.get('dataAssinatura'),
            'tipoPessoa': it.get('tipoPessoa'),
            'niFornecedor': it.get('niFornecedor'),
            'nomeRazaoSocialFornecedor': it.get('nomeRazaoSocialFornecedor'),
            'valorGlobal': it.get('valorGlobal'),
            'orgaoEntidade_razaoSocial': org.get('razaoSocial'),
            'orgaoEntidade_cnpj': org.get('cnpj'),
            'orgaoEntidade_esferaId': org.get('esferaId'),
        })
        wrote += 1
    return wrote


def run_range_mode(session: requests.Session, first: dict, data_inicial: str, data_final: str, total_paginas_api: int, total_registros_api: int) -> None:
    page_start = max(1, int(PAGE_START_RAW))
    page_end = min(total_paginas_api, int(PAGE_END_RAW))
    if page_end < page_start:
        raise ValueError(f'Faixa invalida: start={page_start}, end={page_end}')

    out = OUT
    validation_out = VALIDATION_OUT
    if str(VALIDATION_OUT).endswith('pncp_download_validation.json'):
        validation_out = Path(f"mvp_score/resultados/pncp_validation_{out.stem}.json")

    out.parent.mkdir(parents=True, exist_ok=True)
    total_rows = 0
    failed_pages: list[dict] = []

    print(f'[RANGE] Janela PNCP: {data_inicial}->{data_final}')
    print(f'[RANGE] totalRegistros(API)={total_registros_api} | totalPaginas(API)={total_paginas_api}')
    print(f'[RANGE] Baixando paginas {page_start}..{page_end} em {out}')

    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()

        for pagina in range(page_start, page_end + 1):
            try:
                payload = first if pagina == 1 else fetch_page(session, data_inicial, data_final, pagina=pagina, tamanho_pagina=PAGE_SIZE)
            except Exception as e:
                if CONTINUE_ON_PAGE_ERROR:
                    failed_pages.append({'pagina': pagina, 'erro': str(e)})
                    print(f'[RANGE][WARN] pagina {pagina} falhou definitivamente. Continuando. erro={e}')
                    continue
                raise
            data = payload.get('data') or []
            if not data:
                print(f'[RANGE] pagina {pagina} sem dados. Encerrando faixa.')
                page_end = pagina - 1
                break

            total_rows += write_rows_for_page(w, data)
            if pagina % 25 == 0 or pagina == page_start or pagina == page_end:
                print(f'[RANGE] pagina={pagina}/{total_paginas_api} rows={total_rows}')

            if SLEEP_BETWEEN > 0:
                time.sleep(SLEEP_BETWEEN)

    failed_path = validation_out.with_name(f'failed_pages_{out.stem}.csv')
    write_failed_pages_csv(failed_path, failed_pages)

    validation = {
        'mode': 'range',
        'data_inicial': data_inicial,
        'data_final': data_final,
        'page_size': PAGE_SIZE,
        'total_paginas_api': total_paginas_api,
        'total_registros_api': total_registros_api,
        'page_start': page_start,
        'page_end': page_end,
        'rows_written': total_rows,
        'failed_pages_count': len(failed_pages),
        'failed_pages_file': str(failed_path),
        'csv_path': str(out),
        'download_finalizado_paginas': bool(page_end >= total_paginas_api and page_start == 1),
        'download_integral': bool(page_end >= total_paginas_api and page_start == 1 and total_rows == total_registros_api),
    }
    write_json(validation_out, validation)
    print(f'[RANGE] CSV gerado: {out} | rows={total_rows}')
    print(f'[RANGE] Validacao: {validation_out}')


def run_sequential_mode(session: requests.Session, first: dict, state: dict | None, data_inicial: str, data_final: str, total_paginas_api: int, total_registros_api: int) -> None:
    if state is None:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
        next_page = 1
        rows_written = 0
    else:
        next_page = int(state.get('next_page', 1))
        rows_written = int(state.get('rows_written', 0))

    if next_page > total_paginas_api:
        print('Download ja completo segundo state file.')
        return

    end_page = min(total_paginas_api, next_page + PAGE_BATCH - 1)
    failed_pages: list[dict] = []

    print(f'Janela PNCP: {data_inicial}->{data_final}')
    print(f'totalRegistros(API)={total_registros_api} | totalPaginas(API)={total_paginas_api}')
    print(f'Executando lote de paginas: {next_page}..{end_page} (batch={PAGE_BATCH})')

    with OUT.open('a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)

        for pagina in range(next_page, end_page + 1):
            try:
                payload = first if pagina == 1 else fetch_page(session, data_inicial, data_final, pagina=pagina, tamanho_pagina=PAGE_SIZE)
            except Exception as e:
                if CONTINUE_ON_PAGE_ERROR:
                    failed_pages.append({'pagina': pagina, 'erro': str(e)})
                    print(f'[WARN] pagina {pagina} falhou definitivamente. Continuando. erro={e}')
                    write_json(STATE_PATH, {
                        'data_inicial': data_inicial,
                        'data_final': data_final,
                        'page_size': PAGE_SIZE,
                        'total_paginas_api': total_paginas_api,
                        'total_registros_api': total_registros_api,
                        'next_page': pagina + 1,
                        'rows_written': rows_written,
                        'last_updated_epoch': int(time.time()),
                    })
                    continue
                raise
            data = payload.get('data') or []
            if not data:
                print(f'Fim na pagina {pagina} (sem dados).')
                end_page = pagina - 1
                break

            rows_written += write_rows_for_page(w, data)

            if pagina % 25 == 0 or pagina == next_page or pagina == end_page:
                print(f'pagina={pagina}/{total_paginas_api} total_rows={rows_written}')

            write_json(STATE_PATH, {
                'data_inicial': data_inicial,
                'data_final': data_final,
                'page_size': PAGE_SIZE,
                'total_paginas_api': total_paginas_api,
                'total_registros_api': total_registros_api,
                'next_page': pagina + 1,
                'rows_written': rows_written,
                'last_updated_epoch': int(time.time()),
            })

            if SLEEP_BETWEEN > 0:
                time.sleep(SLEEP_BETWEEN)

    complete = (end_page >= total_paginas_api)
    failed_path = VALIDATION_OUT.with_name('failed_pages_sequential.csv')
    write_failed_pages_csv(failed_path, failed_pages)

    validation = {
        'mode': 'sequential',
        'data_inicial': data_inicial,
        'data_final': data_final,
        'page_size': PAGE_SIZE,
        'total_paginas_api': total_paginas_api,
        'total_registros_api': total_registros_api,
        'ultimo_lote_inicio': next_page,
        'ultimo_lote_fim': end_page,
        'rows_written': rows_written,
        'next_page': end_page + 1,
        'failed_pages_count': len(failed_pages),
        'failed_pages_file': str(failed_path),
        'download_integral': bool(complete and rows_written == total_registros_api),
        'download_finalizado_paginas': bool(complete),
        'csv_path': str(OUT),
        'state_path': str(STATE_PATH),
    }
    write_json(VALIDATION_OUT, validation)

    print(f'CSV atualizado: {OUT} | rows_written={rows_written}')
    print(f'State: {STATE_PATH}')
    print(f'Validacao: {VALIDATION_OUT}')


def main():
    # Em RANGE_MODE, evitar ambiguidade de janela entre terminais paralelos.
    if RANGE_MODE and not (FIXED_DATA_INICIAL and FIXED_DATA_FINAL):
        raise RuntimeError('No modo de faixa (PNCP_PAGE_START/PNCP_PAGE_END), defina PNCP_DATA_INICIAL e PNCP_DATA_FINAL explicitamente.')

    state = None
    if (not RANGE_MODE) and RESUME and STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding='utf-8'))

    data_inicial, data_final = resolve_window(state)

    if (not RANGE_MODE) and state is not None:
        mismatch = (
            state.get('data_inicial') != data_inicial
            or state.get('data_final') != data_final
            or state.get('page_size') != PAGE_SIZE
        )
        if mismatch:
            msg = (
                'State existente nao corresponde aos parametros atuais. '
                f"state=({state.get('data_inicial')}..{state.get('data_final')}, page_size={state.get('page_size')}), "
                f'params=({data_inicial}..{data_final}, page_size={PAGE_SIZE}).'
            )
            if STRICT_RESUME:
                raise RuntimeError(
                    msg
                    + ' Abortei para evitar sobrescrever progresso. '
                    'Use PNCP_STRICT_RESUME=0 para iniciar novo ciclo, ou ajuste PNCP_DATA_INICIAL/PNCP_DATA_FINAL para casar com o state.'
                )
            print('[INFO] ' + msg + ' Iniciando novo ciclo por PNCP_STRICT_RESUME=0.')
            state = None

    session = requests.Session()
    session.headers.update({'accept': '*/*', 'user-agent': 'mvp-score-mei/1.0'})

    first = fetch_page(session, data_inicial, data_final, pagina=1, tamanho_pagina=PAGE_SIZE)
    total_registros_api = int(first.get('totalRegistros') or 0)
    total_paginas_api = int(first.get('totalPaginas') or 0)

    if RANGE_MODE:
        run_range_mode(session, first, data_inicial, data_final, total_paginas_api, total_registros_api)
    else:
        run_sequential_mode(session, first, state, data_inicial, data_final, total_paginas_api, total_registros_api)


if __name__ == '__main__':
    main()
