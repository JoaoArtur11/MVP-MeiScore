# plot_kpis_mei_pncp.py
# Gera gráficos (PNG) + um HTML simples de apresentação
# a partir das tabelas kpi_* no DuckDB.
#
# Requisitos:
#   pip install duckdb pandas matplotlib
#
# Uso:
#   python plot_kpis_mei_pncp.py
#
# Saídas:
#   ./out_charts/*.png
#   ./out_charts/relatorio_mei_pncp.html

from pathlib import Path
import duckdb
import pandas as pd
import matplotlib.pyplot as plt
from project_paths import DB_PATH, OUT_CHARTS_DIR

OUT_DIR = OUT_CHARTS_DIR


def fmt_pct(x: float) -> str:
    return f"{x*100:.4f}%"


def fmt_money_br(x: float) -> str:
    # simples e legível (não depende de locale)
    if x >= 1e9:
        return f"R$ {x/1e9:.2f} bi"
    if x >= 1e6:
        return f"R$ {x/1e6:.2f} mi"
    if x >= 1e3:
        return f"R$ {x/1e3:.2f} mil"
    return f"R$ {x:.2f}"


def ensure_out():
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def save_bar(df, xcol, ycol, title, xlabel, ylabel, filename, rotate=0, figsize=(10, 6)):
    plt.figure(figsize=figsize)
    plt.bar(df[xcol].astype(str), df[ycol])
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    if rotate:
        plt.xticks(rotation=rotate, ha="right")
    plt.tight_layout()
    plt.savefig(OUT_DIR / filename, dpi=160)
    plt.close()


def save_barh(df, xcol, ycol, title, xlabel, ylabel, filename, figsize=(12, 7)):
    # Horizontal é melhor para rótulos longos (ex.: nomes de órgãos)
    plt.figure(figsize=figsize)
    plt.barh(df[xcol].astype(str), df[ycol])
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.gca().invert_yaxis()  # maior valor no topo
    plt.tight_layout()
    plt.savefig(OUT_DIR / filename, dpi=160)
    plt.close()


def save_line(df, xcol, ycol, title, xlabel, ylabel, filename, rotate=0, figsize=(10, 6)):
    plt.figure(figsize=figsize)
    plt.plot(df[xcol], df[ycol])
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    if rotate:
        plt.xticks(rotation=rotate, ha="right")
    plt.tight_layout()
    plt.savefig(OUT_DIR / filename, dpi=160)
    plt.close()


def save_dual_share(kpi_row, filename, figsize=(9, 5)):
    # gráfico simples comparando shares (contratos vs valor)
    labels = ["Share (qtd contratos)", "Share (valor)"]
    values = [kpi_row["share_contratos"], kpi_row["share_valor"]]

    plt.figure(figsize=figsize)
    plt.bar(labels, values)
    plt.title("Participação do MEI nas compras federais (6 meses)")
    plt.ylabel("Proporção")
    plt.tight_layout()
    plt.savefig(OUT_DIR / filename, dpi=160)
    plt.close()


def main():
    ensure_out()

    con = duckdb.connect(str(DB_PATH))

    # =========================
    # 1) KPI principal (participação)
    # =========================
    kpi = con.execute("SELECT * FROM kpi_mei_participacao_federal_6m").fetchdf()
    if kpi.empty:
        raise RuntimeError("Tabela kpi_mei_participacao_federal_6m vazia. Rode o join primeiro.")
    k = kpi.iloc[0].to_dict()

    # salvar KPI em CSV (para usar em relatório)
    pd.DataFrame([k]).to_csv(OUT_DIR / "kpi_participacao.csv", index=False, encoding="utf-8")

    # gráfico share
    save_dual_share(k, "01_share_mei_federal.png")

    # =========================
    # 2) Top UF (valor)
    # =========================
    uf = con.execute("""
        SELECT uf, qtd_contratos, valor_total
        FROM kpi_mei_top_uf_federal_6m
        ORDER BY valor_total DESC
        LIMIT 10
    """).fetchdf()
    uf.to_csv(OUT_DIR / "kpi_top_uf.csv", index=False, encoding="utf-8")
    save_bar(
        uf, "uf", "valor_total",
        "Top 10 UF do MEI (por valor) - Federal (6 meses)",
        "UF", "Valor total (R$ em milhões)",
        "02_top_uf_valor.png",
        rotate=0,
        figsize=(9, 5)
    )

    # =========================
    # 3) Série diária (valor)
    # =========================
    serie = con.execute("""
        SELECT dia, qtd_contratos, valor_total
        FROM kpi_mei_serie_diaria_federal_6m
        ORDER BY dia
    """).fetchdf()
    serie.to_csv(OUT_DIR / "kpi_serie_diaria.csv", index=False, encoding="utf-8")

    # Para melhorar legibilidade:
    # - figura mais larga
    # - rotação moderada
    save_line(
        serie, "dia", "valor_total",
        "Série diária (valor) - MEI no Federal (6 meses)",
        "Dia", "Valor total (R$ em milhões)",
        "03_serie_diaria_valor.png",
        rotate=45,
        figsize=(11, 5.5)
    )

    # =========================
    # 4) Top CNAE (valor)
    # =========================
    cnae = con.execute("""
        SELECT cnae, qtd_contratos, valor_total
        FROM kpi_mei_top_cnae_federal_6m
        ORDER BY valor_total DESC
        LIMIT 15
    """).fetchdf()
    cnae.to_csv(OUT_DIR / "kpi_top_cnae.csv", index=False, encoding="utf-8")

    # CNAE pode ser vertical com rotação
    save_bar(
        cnae, "cnae", "valor_total",
        "Top 15 CNAE do MEI (por valor) - Federal (6 meses)",
        "CNAE", "Valor total (R$ em milhões)",
        "04_top_cnae_valor.png",
        rotate=45,
        figsize=(11, 6)
    )

    # =========================
    # 5) Top órgãos (valor) - FIX: gráfico horizontal + truncagem
    # =========================
    org = con.execute("""
        SELECT orgao_razao, qtd_contratos, valor_total
        FROM kpi_mei_top_orgaos_federal_6m
        ORDER BY valor_total DESC
        LIMIT 15
    """).fetchdf()
    org.to_csv(OUT_DIR / "kpi_top_orgaos.csv", index=False, encoding="utf-8")

    # Truncar nomes para não “explodir” o layout (mantém legível no horizontal)
    org["orgao_razao"] = org["orgao_razao"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip().str.slice(0, 70)

    # ✅ horizontal (não corta mais)
    save_barh(
        org, "orgao_razao", "valor_total",
        "Top 15 órgãos federais (por valor MEI) - 6 meses",
        "Valor total (R$ em milhões)", "Órgão",
        "05_top_orgaos_valor.png",
        figsize=(12, 7.5)
    )

    # =========================
    # 6) HTML simples de apresentação
    # =========================
    share_contratos = fmt_pct(float(k["share_contratos"]))
    share_valor = fmt_pct(float(k["share_valor"]))
    valor_mei = fmt_money_br(float(k["valor_mei"]))
    valor_total = fmt_money_br(float(k["valor_total"]))

    html = f"""
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8"/>
  <title>Panorama MEI nas Compras Federais (PNCP) - 6 meses</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; }}
    .kpis {{ display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 14px; }}
    .card h3 {{ margin: 0 0 8px 0; font-size: 14px; color: #333; }}
    .card .v {{ font-size: 22px; font-weight: 700; }}
    img {{ max-width: 100%; margin: 14px 0; border: 1px solid #eee; border-radius: 10px; }}
    .note {{ color: #555; font-size: 12px; margin-top: 10px; }}
  </style>
</head>
<body>
  <h1>Panorama de participação do MEI nas compras federais (PNCP) — últimos 6 meses</h1>

  <div class="kpis">
    <div class="card">
      <h3>Participação por quantidade (MEI)</h3>
      <div class="v">{share_contratos}</div>
      <div class="note">{int(k["contratos_mei"]):,} de {int(k["contratos_total"]):,} contratos</div>
    </div>
    <div class="card">
      <h3>Participação por valor (MEI)</h3>
      <div class="v">{share_valor}</div>
      <div class="note">{valor_mei} de {valor_total}</div>
    </div>
  </div>

  <h2>Comparativo de participação (qtd vs valor)</h2>
  <img src="01_share_mei_federal.png" alt="Share"/>

  <h2>Distribuição geográfica do MEI vendedor (Top UF)</h2>
  <img src="02_top_uf_valor.png" alt="Top UF"/>

  <h2>Evolução temporal (série diária)</h2>
  <img src="03_serie_diaria_valor.png" alt="Série diária"/>

  <h2>Perfil econômico (Top CNAE)</h2>
  <img src="04_top_cnae_valor.png" alt="Top CNAE"/>

  <h2>Órgãos federais com maior valor contratado com MEI</h2>
  <img src="05_top_orgaos_valor.png" alt="Top Órgãos"/>

  <p class="note">
    Fonte: PNCP (Contratos/Empenhos) cruzado com MEI ativo (RFB/Simples) no DuckDB.
    Observação: contratos com fornecedor tipoPessoa != PJ ou sem CNPJ válido não entram no cruzamento com MEI.
  </p>
</body>
</html>
"""
    out_html = OUT_DIR / "relatorio_mei_pncp.html"
    out_html.write_text(html, encoding="utf-8")

    con.close()
    print("\n✅ OK - Gráficos gerados em:", OUT_DIR)
    print("✅ OK - HTML:", out_html)


if __name__ == "__main__":
    main()
