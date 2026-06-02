from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTADOS_DIR = PROJECT_ROOT / 'mvp_score' / 'resultados'
SCORE_PATH = RESULTADOS_DIR / 'score_oportunidade.csv'
VALID_UFS = {
    'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO',
    'MA', 'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI',
    'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
}
CNAE_DESCRICOES = {
    '4321500': 'Instalacao e manutencao eletrica',
    '4399103': 'Obras de alvenaria',
    '4520005': 'Servicos de lavagem, lubrificacao e polimento de veiculos',
    '4541206': 'Comercio de pecas e acessorios para motocicletas',
    '4712100': 'Comercio varejista de mercadorias em geral',
    '5611203': 'Lanchonetes, casas de cha, sucos e similares',
    '7319002': 'Promocao de vendas',
    '7420001': 'Atividades de producao de fotografias',
    '7729202': 'Aluguel de moveis, utensilios e aparelhos de uso domestico e pessoal',
    '8230001': 'Servicos de organizacao de feiras, congressos e exposicoes',
    '9001902': 'Producao musical',
    '9511800': 'Reparacao e manutencao de computadores e perifericos',
}


st.set_page_config(
    page_title='Score de Oportunidade MEI',
    layout='wide',
)


st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(32, 86, 67, 0.16), transparent 28rem),
            linear-gradient(180deg, #f8f5ee 0%, #fffaf0 100%);
        color: #17231f;
    }
    .hero {
        padding: 1.35rem 1.5rem;
        border-radius: 1.2rem;
        background: linear-gradient(135deg, #173f35 0%, #245e4e 58%, #d99f43 100%);
        color: #fffaf0;
        margin-bottom: 1.2rem;
    }
    .hero h1 {
        margin: 0 0 .35rem 0;
        font-size: 2.1rem;
        line-height: 1.05;
        letter-spacing: -0.04em;
    }
    .hero p {
        margin: 0;
        max-width: 70rem;
        color: #f7ead3;
        font-size: 1.02rem;
    }
    .metric-card {
        padding: 1rem;
        border-radius: 1rem;
        background: rgba(255, 255, 255, .74);
        border: 1px solid rgba(23, 63, 53, .12);
        box-shadow: 0 8px 24px rgba(42, 54, 45, .08);
    }
    .small-note {
        color: #5d655f;
        font-size: .9rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def normalize_score_df(df: pd.DataFrame) -> pd.DataFrame:
    required = ['CNAE', 'UF', 'score', 'ranking', 'count_contratos', 'valor_medio', 'n_orgaos']
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f'Colunas obrigatorias ausentes: {missing}')

    df = df.copy()
    df['CNAE'] = df['CNAE'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    df['UF'] = df['UF'].astype(str).str.upper().str.strip()
    df['score'] = pd.to_numeric(df['score'], errors='coerce').fillna(0.0)
    df['ranking'] = pd.to_numeric(df['ranking'], errors='coerce').fillna(0).astype(int)
    df['count_contratos'] = pd.to_numeric(df['count_contratos'], errors='coerce').fillna(0).astype(int)
    df['valor_medio'] = pd.to_numeric(df['valor_medio'], errors='coerce').fillna(0.0)
    df['n_orgaos'] = pd.to_numeric(df['n_orgaos'], errors='coerce').fillna(0).astype(int)
    df['descricao_cnae'] = df['CNAE'].map(CNAE_DESCRICOES).fillna('Descricao nao cadastrada')
    df['CNAE_legenda'] = df['CNAE'] + ' - ' + df['descricao_cnae']
    return df.sort_values(['ranking', 'score'], ascending=[True, False]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_score_file(path: str) -> pd.DataFrame:
    return normalize_score_df(pd.read_csv(path))


def format_brl(value: float) -> str:
    text = f'R$ {value:,.2f}'
    return text.replace(',', 'X').replace('.', ',').replace('X', '.')


def score_band(score: float) -> tuple[str, str]:
    if score >= 80:
        return 'Alta oportunidade historica', 'Perfil com forte sinal historico de contratacao publica.'
    if score >= 50:
        return 'Oportunidade intermediaria', 'Perfil com algum sinal historico, mas abaixo dos lideres.'
    return 'Baixa oportunidade historica', 'Perfil com pouco sinal historico na janela analisada.'


def cnae_label(cnae: str) -> str:
    return f'{cnae} - {CNAE_DESCRICOES.get(str(cnae), "Descricao nao cadastrada")}'


def show_missing_data_state() -> None:
    st.warning('Arquivo score_oportunidade.csv ainda nao encontrado.')
    st.markdown(
        """
        Para usar o dashboard, primeiro gere a saida final do MVP.

        Modo de amostra pequena:

        ```powershell
        python mvp_score/gerar_amostra_demo.py
        $env:MVP_BASE_DIR='amostra_dados'
        python mvp_score/fase1_preparacao.py
        python mvp_score/fase2_features.py
        python mvp_score/fase3_modelos.py
        python mvp_score/fase4_visualizacoes.py
        streamlit run mvp_score/dashboard.py
        ```

        Modo real:

        ```powershell
        python mvp_score/fase1_preparacao.py
        python mvp_score/fase2_features.py
        python mvp_score/fase3_modelos.py
        python mvp_score/fase4_visualizacoes.py
        streamlit run mvp_score/dashboard.py
        ```
        """
    )


st.markdown(
    """
    <div class="hero">
      <h1>Score de Oportunidade MEI</h1>
      <p>
        Consulte a probabilidade historica estimada de contratacao publica federal
        por combinacao de CNAE e UF. O score resume sinais observados no PNCP e
        na base publica CNPJ/MEI da Receita Federal.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

uploaded_file = st.sidebar.file_uploader(
    'Opcional: carregar score_oportunidade.csv',
    type=['csv'],
    help='Use apenas se quiser analisar um arquivo gerado em outra execucao.',
)

try:
    if uploaded_file is not None:
        df = normalize_score_df(pd.read_csv(uploaded_file))
        source_label = 'arquivo carregado manualmente'
    elif SCORE_PATH.exists():
        df = load_score_file(str(SCORE_PATH))
        source_label = str(SCORE_PATH.relative_to(PROJECT_ROOT))
    else:
        show_missing_data_state()
        st.stop()
except Exception as exc:
    st.error(f'Nao foi possivel carregar o score: {exc}')
    st.stop()

invalid_ufs = sorted(set(df.loc[~df['UF'].isin(VALID_UFS), 'UF'].dropna().astype(str)))
if invalid_ufs:
    st.warning(
        'Foram encontrados valores que nao sao siglas de UF validas: '
        + ', '.join(invalid_ufs[:12])
        + ('.' if len(invalid_ufs) <= 12 else '...')
    )

st.caption(f'Fonte da consulta: `{source_label}`')

left, right = st.columns([0.34, 0.66], gap='large')

with left:
    st.subheader('Consulta')
    uf_options = ['Todas'] + sorted(df['UF'].dropna().unique().tolist())
    selected_uf = st.selectbox('UF', uf_options)

    cnae_base = df if selected_uf == 'Todas' else df[df['UF'] == selected_uf]
    cnae_options = sorted(cnae_base['CNAE'].dropna().unique().tolist())
    selected_cnae = st.selectbox('CNAE', cnae_options, format_func=cnae_label)

    rows = cnae_base[cnae_base['CNAE'] == selected_cnae].copy()
    if selected_uf == 'Todas':
        uf_for_cnae = sorted(rows['UF'].dropna().unique().tolist())
        selected_uf_detail = st.selectbox('UF para este CNAE', uf_for_cnae)
        rows = rows[rows['UF'] == selected_uf_detail]

    selected = rows.sort_values('score', ascending=False).iloc[0]
    band_title, band_text = score_band(float(selected['score']))

    st.markdown(
        f"""
        <div class="metric-card">
          <div class="small-note">Interpretacao</div>
          <h3>{band_title}</h3>
          <p>{band_text}</p>
          <p class="small-note">
            O score nao garante contrato individual. Ele indica oportunidade historica
            estimada para o perfil CNAE x UF.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with right:
    st.subheader('Resultado para o perfil selecionado')
    st.markdown(f"**CNAE:** `{selected['CNAE']}` - {selected['descricao_cnae']}")
    st.markdown(f"**UF:** `{selected['UF']}`")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric('Score', f'{float(selected["score"]):.1f}/100')
    m2.metric('Ranking', f'{int(selected["ranking"])}')
    m3.metric('Contratos', f'{int(selected["count_contratos"])}')
    m4.metric('Orgaos', f'{int(selected["n_orgaos"])}')
    st.metric('Valor medio contratado', format_brl(float(selected['valor_medio'])))

    st.progress(min(max(float(selected['score']) / 100.0, 0.0), 1.0))

    if str(selected['UF']) not in VALID_UFS:
        st.info(
            'Nota: a UF selecionada nao e uma sigla valida. Isso indica valor herdado '
            'dos dados de entrada ou problema de layout na fonte.'
        )

st.divider()

top10 = df.sort_values(['score', 'ranking'], ascending=[False, True]).head(10).copy()
top10['CNAE x UF'] = top10['CNAE_legenda'] + ' | ' + top10['UF']

chart_col, table_col = st.columns([0.58, 0.42], gap='large')

with chart_col:
    st.subheader('Top 10 por score')
    st.bar_chart(top10.set_index('CNAE x UF')['score'])

with table_col:
    st.subheader('Tabela resumida')
    st.dataframe(
        top10[['ranking', 'CNAE', 'descricao_cnae', 'UF', 'score', 'count_contratos', 'valor_medio', 'n_orgaos']],
        hide_index=True,
        use_container_width=True,
    )

with st.expander('Legenda de CNAEs presentes no resultado'):
    legenda = (
        df[['CNAE', 'descricao_cnae']]
        .drop_duplicates()
        .sort_values('CNAE')
        .reset_index(drop=True)
    )
    st.dataframe(legenda, hide_index=True, use_container_width=True)

st.divider()
st.subheader('Graficos demonstrativos do pipeline')

graph_cols = st.columns(4)
graph_files = [
    ('Top 10', RESULTADOS_DIR / 'grafico_top10.png'),
    ('ROC', RESULTADOS_DIR / 'grafico_roc.png'),
    ('Confusao', RESULTADOS_DIR / 'grafico_confusao.png'),
    ('Metricas', RESULTADOS_DIR / 'grafico_metricas.png'),
]

for col, (title, path) in zip(graph_cols, graph_files):
    with col:
        st.caption(title)
        if path.exists():
            st.image(str(path), use_container_width=True)
        else:
            st.info('Gerado apos executar a Fase 4.')
