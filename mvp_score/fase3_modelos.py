import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier


def _metricas(y_true, y_pred, y_prob):
    return {
        'F1': f1_score(y_true, y_pred, zero_division=0),
        'AUC-ROC': roc_auc_score(y_true, y_prob) if len(np.unique(y_true)) > 1 else np.nan,
        'Precisão': precision_score(y_true, y_pred, zero_division=0),
        'Recall': recall_score(y_true, y_pred, zero_division=0),
    }


def _selecionar_melhor_modelo(metricas_df: pd.DataFrame) -> str:
    """
    Critério oficial de seleção:
    1) maior AUC-ROC
    2) em empate, maior F1
    3) em empate, prioridade para modelo aprendido:
       Regressão Logística > Árvore de Decisão > Baseline
    """
    df = metricas_df.copy()
    df['AUC-ROC'] = df['AUC-ROC'].astype(float)
    df['F1'] = df['F1'].astype(float)

    auc_max = df['AUC-ROC'].max()
    cand = df[np.isclose(df['AUC-ROC'], auc_max, rtol=0, atol=1e-12)].copy()

    f1_max = cand['F1'].max()
    cand = cand[np.isclose(cand['F1'], f1_max, rtol=0, atol=1e-12)].copy()

    priority = {
        'Regressão Logística': 0,
        'Árvore de Decisão': 1,
        'Baseline': 2,
    }
    cand['priority'] = cand['modelo'].map(priority).fillna(99)
    cand = cand.sort_values(['priority', 'modelo'], ascending=[True, True])
    return str(cand.iloc[0]['modelo'])


def phase3_main():
    dados_dir = Path('mvp_score/dados')
    res_dir = Path('mvp_score/resultados')
    dados_dir.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)

    fpath = dados_dir / 'features.csv'
    if not fpath.exists():
        raise FileNotFoundError('Arquivo não encontrado: mvp_score/dados/features.csv. Execute a Fase 2 primeiro.')

    df = pd.read_csv(fpath)

    meta2_path = dados_dir / 'metadata_fase2.json'
    if meta2_path.exists():
        meta2 = json.loads(meta2_path.read_text(encoding='utf-8'))
        feature_cols = meta2['feature_cols']
    else:
        feature_cols = [
            'share_cnae', 'share_uf', 'log_valor_medio', 'log_valor_total',
            'log_count', 'diversidade_orgaos', 'densidade_mei'
        ]

    X = df[feature_cols].copy()
    y = df['target'].astype(int).copy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # BASELINE
    baseline_thr = X_train['log_count'].median()
    y_prob_base = (X_test['log_count'] - X_test['log_count'].min())
    denom = (X_test['log_count'].max() - X_test['log_count'].min())
    y_prob_base = (y_prob_base / denom) if denom > 0 else pd.Series(0.5, index=X_test.index)
    y_pred_base = (X_test['log_count'] >= baseline_thr).astype(int)

    met_base = _metricas(y_test, y_pred_base, y_prob_base)
    cm_base = confusion_matrix(y_test, y_pred_base)

    print('Matriz de confusão - Baseline:')
    print(cm_base)

    # Regressão Logística
    pipe_lr = Pipeline([
        ('scaler', StandardScaler()),
        ('clf', LogisticRegression(max_iter=1000, random_state=42)),
    ])
    pipe_lr.fit(X_train, y_train)
    y_prob_lr = pipe_lr.predict_proba(X_test)[:, 1]
    y_pred_lr = pipe_lr.predict(X_test)

    met_lr = _metricas(y_test, y_pred_lr, y_prob_lr)
    cm_lr = confusion_matrix(y_test, y_pred_lr)
    print('Matriz de confusão - Regressão Logística:')
    print(cm_lr)

    # Árvore de Decisão
    tree = DecisionTreeClassifier(max_depth=5, random_state=42)
    tree.fit(X_train, y_train)
    y_prob_tree = tree.predict_proba(X_test)[:, 1]
    y_pred_tree = tree.predict(X_test)

    met_tree = _metricas(y_test, y_pred_tree, y_prob_tree)
    cm_tree = confusion_matrix(y_test, y_pred_tree)
    print('Matriz de confusão - Árvore de Decisão:')
    print(cm_tree)

    metricas_df = pd.DataFrame([
        {'modelo': 'Baseline', **met_base},
        {'modelo': 'Regressão Logística', **met_lr},
        {'modelo': 'Árvore de Decisão', **met_tree},
    ])

    metricas_df.to_csv(res_dir / 'tabela_metricas.csv', index=False, encoding='utf-8')

    best_model_name = _selecionar_melhor_modelo(metricas_df)
    print(f"Melhor modelo (criterio AUC -> F1 -> prioridade): {best_model_name}")

    if best_model_name == 'Regressão Logística':
        best_model = pipe_lr
    elif best_model_name == 'Árvore de Decisão':
        best_model = tree
    else:
        best_model = None

    artifacts = {
        'feature_cols': feature_cols,
        'baseline_threshold': float(baseline_thr),
        'best_model_name': best_model_name,
        'X_test': X_test,
        'y_test': y_test,
        'y_prob_base': np.asarray(y_prob_base),
        'y_pred_base': np.asarray(y_pred_base),
        'y_prob_lr': y_prob_lr,
        'y_pred_lr': y_pred_lr,
        'y_prob_tree': y_prob_tree,
        'y_pred_tree': y_pred_tree,
        'cm_lr': cm_lr,
        'cm_tree': cm_tree,
    }

    with open(res_dir / 'artifacts_fase3.pkl', 'wb') as f:
        pickle.dump(artifacts, f)

    with open(res_dir / 'best_model.pkl', 'wb') as f:
        pickle.dump(best_model, f)

    (res_dir / 'best_model_name.txt').write_text(best_model_name, encoding='utf-8')

    print(metricas_df)
    print('OK - Fase 3 concluida com sucesso.')


if __name__ == '__main__':
    phase3_main()
