import json
from pathlib import Path

import numpy as np
import pandas as pd


def phase2_main():
    Path('mvp_score/dados').mkdir(parents=True, exist_ok=True)
    Path('mvp_score/resultados').mkdir(parents=True, exist_ok=True)

    in_path = Path('mvp_score/dados/tabela_cnae_uf.csv')
    if not in_path.exists():
        raise FileNotFoundError('Arquivo não encontrado: mvp_score/dados/tabela_cnae_uf.csv. Execute a Fase 1 primeiro.')

    df = pd.read_csv(in_path)

    # Garantir tipos numéricos
    for col in ['count_contratos', 'valor_total', 'valor_medio', 'n_orgaos', 'n_meis']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    total_contratos = df['count_contratos'].sum()

    cnae_sum = df.groupby('CNAE', dropna=False)['count_contratos'].transform('sum')
    uf_sum = df.groupby('UF', dropna=False)['count_contratos'].transform('sum')

    df['share_cnae'] = np.where(total_contratos > 0, cnae_sum / total_contratos, 0.0)
    df['share_uf'] = np.where(total_contratos > 0, uf_sum / total_contratos, 0.0)
    df['log_valor_medio'] = np.log1p(df['valor_medio'].clip(lower=0).fillna(0))
    df['log_valor_total'] = np.log1p(df['valor_total'].clip(lower=0).fillna(0))
    df['log_count'] = np.log1p(df['count_contratos'].clip(lower=0).fillna(0))

    max_orgaos = df['n_orgaos'].max()
    df['diversidade_orgaos'] = np.where(max_orgaos and max_orgaos > 0, df['n_orgaos'] / max_orgaos, 0.0)

    df['densidade_mei'] = np.where(df['count_contratos'] > 0, df['n_meis'] / df['count_contratos'], 0.0)

    # Regra de negocio oficial (fixa):
    # target = 1 para combinacoes CNAE x UF no quartil superior de volume
    # historico de contratos (P75), e 0 para as demais.
    q75_count = float(df['count_contratos'].quantile(0.75))
    df['target'] = (df['count_contratos'] >= q75_count).astype(int)

    if df['target'].nunique() < 2:
        raise RuntimeError(
            'Regra de target resultou em classe unica. '
            'Revise a regra de negocio (percentil) ou a amostra de dados.'
        )

    feature_cols = [
        'share_cnae',
        'share_uf',
        'log_valor_medio',
        'log_valor_total',
        'log_count',
        'diversidade_orgaos',
        'densidade_mei',
    ]

    df[feature_cols] = df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)

    print('Balanceamento target:')
    print(df['target'].value_counts(dropna=False))

    corr = df[feature_cols + ['target']].corr(numeric_only=True)['target'].sort_values(ascending=False)
    print('\nCorrelação das features com target:')
    print(corr)

    out_path = Path('mvp_score/dados/features.csv')
    df.to_csv(out_path, index=False, encoding='utf-8')

    meta = {
        'feature_cols': feature_cols,
        'target_col': 'target',
        'target_rule': 'target=1 se count_contratos >= percentil_75(count_contratos), senao 0',
        'target_threshold_p75_count_contratos': q75_count,
    }
    Path('mvp_score/dados/metadata_fase2.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

    print('OK - Fase 2 concluida com sucesso.')


if __name__ == '__main__':
    phase2_main()
