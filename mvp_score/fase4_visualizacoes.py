import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.metrics import confusion_matrix, roc_curve, auc


def phase4_main():
    dados_dir = Path('mvp_score/dados')
    res_dir = Path('mvp_score/resultados')
    dados_dir.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)

    features_path = dados_dir / 'features.csv'
    if not features_path.exists():
        raise FileNotFoundError('Arquivo não encontrado: mvp_score/dados/features.csv. Execute a Fase 2 primeiro.')

    artifacts_path = res_dir / 'artifacts_fase3.pkl'
    model_path = res_dir / 'best_model.pkl'
    metricas_path = res_dir / 'tabela_metricas.csv'

    if not artifacts_path.exists() or not model_path.exists() or not metricas_path.exists():
        raise FileNotFoundError('Artefatos da Fase 3 não encontrados. Execute a Fase 3 primeiro.')

    df = pd.read_csv(features_path)
    metricas_df = pd.read_csv(metricas_path)

    with open(artifacts_path, 'rb') as f:
        artifacts = pickle.load(f)

    with open(model_path, 'rb') as f:
        best_model = pickle.load(f)

    feature_cols = artifacts['feature_cols']
    best_model_name = Path(res_dir / 'best_model_name.txt').read_text(encoding='utf-8').strip()

    X_all = df[feature_cols]

    if best_model is not None:
        score = best_model.predict_proba(X_all)[:, 1] * 100.0
    else:
        thr = artifacts['baseline_threshold']
        # normalização simples para score baseline
        lc = df['log_count']
        denom = (lc.max() - lc.min())
        prob = ((lc - lc.min()) / denom) if denom > 0 else pd.Series(0.5, index=df.index)
        score = prob * 100.0

    df['score'] = np.round(score, 1)
    df = df.sort_values('score', ascending=False).reset_index(drop=True)
    df['ranking'] = np.arange(1, len(df) + 1)

    out_score = df[['CNAE', 'UF', 'score', 'ranking', 'count_contratos', 'valor_medio', 'n_orgaos']].copy()
    out_score.to_csv(res_dir / 'score_oportunidade.csv', index=False, encoding='utf-8')

    # Gráfico 1 - Top 10
    top10 = out_score.head(10).copy()
    top10['label'] = top10['CNAE'].astype(str) + ' | ' + top10['UF'].astype(str)

    plt.figure(figsize=(10, 6))
    cmap = plt.cm.viridis(np.linspace(0.2, 0.9, len(top10)))
    plt.barh(top10['label'][::-1], top10['score'][::-1], color=cmap)
    plt.xlabel('Score (0-100)')
    plt.ylabel('CNAE x UF')
    plt.title('Top 10 CNAE x UF por Score de Oportunidade MEI')
    plt.tight_layout()
    plt.savefig(res_dir / 'grafico_top10.png', dpi=150)
    plt.close()

    # Gráfico 2 - Curva ROC comparativa
    y_test = artifacts['y_test']
    y_prob_base = artifacts['y_prob_base']
    y_prob_lr = artifacts['y_prob_lr']
    y_prob_tree = artifacts['y_prob_tree']

    fpr_b, tpr_b, _ = roc_curve(y_test, y_prob_base)
    fpr_lr, tpr_lr, _ = roc_curve(y_test, y_prob_lr)
    fpr_tr, tpr_tr, _ = roc_curve(y_test, y_prob_tree)

    auc_b = auc(fpr_b, tpr_b)
    auc_lr = auc(fpr_lr, tpr_lr)
    auc_tr = auc(fpr_tr, tpr_tr)

    plt.figure(figsize=(8, 6))
    plt.plot(fpr_b, tpr_b, label=f'Baseline (AUC = {auc_b:.2f})')
    plt.plot(fpr_lr, tpr_lr, label=f'Regressão Logística (AUC = {auc_lr:.2f})')
    plt.plot(fpr_tr, tpr_tr, label=f'Árvore de Decisão (AUC = {auc_tr:.2f})')
    plt.plot([0, 1], [0, 1], 'k--', label='Aleatório')
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('Curvas ROC comparativas')
    plt.legend(loc='lower right')
    plt.tight_layout()
    plt.savefig(res_dir / 'grafico_roc.png', dpi=150)
    plt.close()

    # Gráfico 3 - Matrizes de confusão
    cm_lr = np.array(artifacts['cm_lr'])
    cm_tr = np.array(artifacts['cm_tree'])

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    sns.heatmap(cm_lr, annot=True, fmt='d', cmap='Blues', cbar=False, ax=axes[0])
    axes[0].set_title('Regressão Logística')
    axes[0].set_xlabel('Predito')
    axes[0].set_ylabel('Real')

    sns.heatmap(cm_tr, annot=True, fmt='d', cmap='Greens', cbar=False, ax=axes[1])
    axes[1].set_title('Árvore de Decisão')
    axes[1].set_xlabel('Predito')
    axes[1].set_ylabel('Real')

    plt.tight_layout()
    plt.savefig(res_dir / 'grafico_confusao.png', dpi=150)
    plt.close()

    # Gráfico 4 - Tabela de métricas renderizada
    fig, ax = plt.subplots(figsize=(9, 2.2))
    ax.axis('off')
    tbl = ax.table(
        cellText=np.round(metricas_df[['F1', 'AUC-ROC', 'Precisão', 'Recall']].values, 4),
        rowLabels=metricas_df['modelo'].values,
        colLabels=['F1', 'AUC-ROC', 'Precisão', 'Recall'],
        loc='center'
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1.2, 1.4)
    plt.title('Comparativo de Métricas por Modelo', pad=12)
    plt.tight_layout()
    plt.savefig(res_dir / 'grafico_metricas.png', dpi=150)
    plt.close()

    print(f'Melhor modelo reaproveitado da Fase 3: {best_model_name}')
    print('OK - Fase 4 concluida com sucesso.')


if __name__ == '__main__':
    phase4_main()
