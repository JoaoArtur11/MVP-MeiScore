import csv
import glob
import json
import os
from pathlib import Path

PART_GLOB = os.environ.get('PNCP_PART_GLOB', 'pncp_part_*.csv')
OUT = Path(os.environ.get('PNCP_MERGED_OUT', 'pncp_contratos_raw_merged.csv'))
STATS_OUT = Path(os.environ.get('PNCP_MERGE_STATS_JSON', 'mvp_score/resultados/pncp_merge_stats.json'))
KEY_COLUMNS = [c.strip() for c in os.environ.get(
    'PNCP_MERGE_KEY_COLUMNS',
    'numeroControlePncpCompra,numeroContratoEmpenho,niFornecedor,dataPublicacaoPncp,valorGlobal'
).split(',') if c.strip()]


def main():
    files = sorted([Path(p) for p in glob.glob(PART_GLOB)])
    if not files:
        raise FileNotFoundError(f'Nenhum arquivo encontrado para glob: {PART_GLOB}')

    OUT.parent.mkdir(parents=True, exist_ok=True)
    STATS_OUT.parent.mkdir(parents=True, exist_ok=True)

    seen = set()
    rows_in = 0
    rows_out = 0
    duplicates = 0
    header_ref = None

    with OUT.open('w', newline='', encoding='utf-8') as fout:
        writer = None

        for fp in files:
            with fp.open('r', newline='', encoding='utf-8') as fin:
                reader = csv.DictReader(fin)
                header = reader.fieldnames
                if header is None:
                    continue

                if header_ref is None:
                    header_ref = header
                    writer = csv.DictWriter(fout, fieldnames=header_ref)
                    writer.writeheader()
                elif header != header_ref:
                    raise RuntimeError(f'Header incompativel em {fp}. Esperado={header_ref}, recebido={header}')

                missing = [k for k in KEY_COLUMNS if k not in header_ref]
                if missing:
                    raise KeyError(f'Colunas de chave ausentes em {fp}: {missing}')

                for row in reader:
                    rows_in += 1
                    key = tuple((row.get(k) or '').strip() for k in KEY_COLUMNS)
                    if key in seen:
                        duplicates += 1
                        continue
                    seen.add(key)
                    writer.writerow(row)
                    rows_out += 1

    stats = {
        'part_glob': PART_GLOB,
        'input_files': [str(p) for p in files],
        'output_file': str(OUT),
        'rows_input': rows_in,
        'rows_output': rows_out,
        'duplicates_removed': duplicates,
        'key_columns': KEY_COLUMNS,
    }
    STATS_OUT.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'Merge concluido: {OUT}')
    print(f'rows_input={rows_in} | rows_output={rows_out} | duplicates_removed={duplicates}')
    print(f'Stats: {STATS_OUT}')


if __name__ == '__main__':
    main()
