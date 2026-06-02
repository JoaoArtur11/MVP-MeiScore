# Score de Oportunidade MEI em Compras Publicas Federais

Este projeto implementa um MVP para estimar um **score de oportunidade por combinacao CNAE x UF** para Microempreendedores Individuais (MEI) em compras publicas federais brasileiras.

O pipeline cruza:

- contratos publicos federais publicados no PNCP;
- dados cadastrais publicos de CNPJ/MEI da Receita Federal;
- agregacoes historicas por CNAE, UF, valor contratado, orgaos compradores e MEIs contratados.

O resultado principal e o arquivo `mvp_score/resultados/score_oportunidade.csv`, com score de 0 a 100 para cada combinacao `CNAE x UF`.

---

## Objetivo

Validar a hipotese:

> Um modelo preditivo treinado com variaveis historicas de frequencia de contratacao por CNAE, UF e orgao comprador supera um baseline de frequencia simples na identificacao de combinacoes CNAE x UF com alta probabilidade de contratacao, medido por F1-score e AUC-ROC.

---

## Fontes De Dados

### 1. PNCP - Contratos Publicos

Fonte oficial:

- API de consulta do PNCP: `https://pncp.gov.br/api/consulta/v1/contratos`
- Swagger: `https://pncp.gov.br/api/consulta/swagger-ui/index.html`

O projeto baixa contratos pela API paginada do PNCP e grava um CSV local chamado:

```text
pncp_contratos_raw.csv
```

Colunas usadas no MVP:

- `niFornecedor`: CNPJ do fornecedor.
- `tipoPessoa`: identifica pessoa juridica (`PJ`) ou pessoa fisica.
- `valorGlobal`: valor global do contrato.
- `dataPublicacaoPncp`: data de publicacao no PNCP.
- `orgaoEntidade_razaoSocial`: orgao comprador.

Como baixar para uma janela fixa:

```powershell
$env:PNCP_DATA_INICIAL='20251127'
$env:PNCP_DATA_FINAL='20260530'
$env:PNCP_PAGE_SIZE='500'
$env:PNCP_SLEEP_SECONDS='0.05'
$env:PNCP_RETRY_FOREVER='1'
$env:PNCP_MAX_RETRIES='999999'
$env:PNCP_PAGE_BATCH='5000'
$env:PNCP_RESUME='1'
$env:PNCP_STRICT_RESUME='1'
$env:PNCP_OUT_CSV='pncp_contratos_raw.csv'
$env:PNCP_VALIDATION_JSON='mvp_score/resultados/pncp_download_validation.json'
python mvp_score/gerar_pncp_csv.py
```

Observacoes:

- Ajuste `PNCP_DATA_INICIAL` e `PNCP_DATA_FINAL` para a janela desejada.
- O PNCP pode oscilar e retornar erros 5xx; por isso o script tem retries.
- O script consulta a primeira pagina para descobrir `totalPaginas` e segue ate o fim da janela.
- Para janela dinamica dos ultimos dias, remova `PNCP_DATA_INICIAL` e `PNCP_DATA_FINAL` e defina `PNCP_DAYS_BACK`.
- O CSV precisa ficar na raiz do projeto, pois a fase 1 identifica automaticamente `pncp_contratos_raw.csv`.

---

### 2. Receita Federal - Base Publica CNPJ / MEI

Fonte oficial:

- Portal de dados abertos CNPJ: `https://dadosabertos.rfb.gov.br/CNPJ/`
- Diretorio de arquivos: `https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/`

O MVP precisa dos seguintes conjuntos:

- `Empresas0.zip` a `Empresas9.zip`
- `Estabelecimentos0.zip` a `Estabelecimentos9.zip`
- `Simples.zip`

Arquivos auxiliares como `Cnaes.zip`, `Municipios.zip`, `Naturezas.zip`, `Socios*.zip`, `Paises.zip`, `Motivos.zip` e `Qualificacoes.zip` nao sao necessarios para este MVP.

Estrutura esperada no projeto depois de baixar e extrair:

```text
rf_cnpj_csv/
  _extracted/
    2026-05-10/
      K3241.K03200Y0.D60509.ESTABELE
      K3241.K03200Y1.D60509.ESTABELE
      ...
      K3241.K03200Y9.D60509.ESTABELE
      K3241.K03200Y1.D60509.EMPRECSV
      ...
      K3241.K03200Y9.D60509.EMPRECSV
      F.K03200$W.SIMPLES.CSV.D60509
```

Como baixar manualmente:

1. Acesse `https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/`.
2. Entre no mes mais recente disponivel.
3. Baixe os arquivos `Empresas*.zip`, `Estabelecimentos*.zip` e `Simples.zip`.
4. Extraia todos para `rf_cnpj_csv/_extracted/<data-do-snapshot>/`.

Exemplo PowerShell para baixar um snapshot especifico:

```powershell
$base='https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/2026-05/'
$out='dados cnae/2026-05'
New-Item -ItemType Directory -Force -Path $out

0..9 | ForEach-Object {
  Invoke-WebRequest "${base}Empresas$_.zip" -OutFile "$out/Empresas$_.zip"
  Invoke-WebRequest "${base}Estabelecimentos$_.zip" -OutFile "$out/Estabelecimentos$_.zip"
}
Invoke-WebRequest "${base}Simples.zip" -OutFile "$out/Simples.zip"
```

Depois extraia os ZIPs:

```powershell
$snapshot='2026-05-10'
$src='dados cnae/2026-05'
$dst="rf_cnpj_csv/_extracted/$snapshot"
New-Item -ItemType Directory -Force -Path $dst
Get-ChildItem $src -Filter *.zip | ForEach-Object {
  Expand-Archive -Path $_.FullName -DestinationPath $dst -Force
}
```

Observacoes:

- A Receita publica arquivos sem cabecalho.
- O separador e `;`.
- Os arquivos sao grandes; reserve dezenas de GB para download e extracao.
- A fase 1 seleciona automaticamente o snapshot mais recente encontrado em `rf_cnpj_csv/_extracted/`.

---

## Dados Derivados Gerados Pelo MVP

A fase 1 cruza PNCP e Receita Federal por CNPJ normalizado e gera:

```text
mvp_score/dados/tabela_cnae_uf.csv
```

Colunas:

- `CNAE`
- `UF`
- `count_contratos`
- `valor_total`
- `valor_medio`
- `n_orgaos`
- `n_meis`

A fase 2 cria:

```text
mvp_score/dados/features.csv
```

Features:

- `share_cnae`
- `share_uf`
- `log_valor_medio`
- `log_valor_total`
- `log_count`
- `diversidade_orgaos`
- `densidade_mei`

Target:

- `target = 1` se `count_contratos >= P75(count_contratos)`;
- `target = 0` caso contrario.

---

## Como Executar O MVP

Depois de obter os dados brutos:

```powershell
python mvp_score/fase1_preparacao.py
python mvp_score/fase2_features.py
python mvp_score/fase3_modelos.py
python mvp_score/fase4_visualizacoes.py
```

Saidas principais:

```text
mvp_score/dados/tabela_cnae_uf.csv
mvp_score/dados/features.csv
mvp_score/resultados/tabela_metricas.csv
mvp_score/resultados/score_oportunidade.csv
mvp_score/resultados/grafico_top10.png
mvp_score/resultados/grafico_roc.png
mvp_score/resultados/grafico_confusao.png
mvp_score/resultados/grafico_metricas.png
```

---

## Estrutura Principal

```text
projeto_memp/
  pncp_contratos_raw.csv
  rf_cnpj_csv/
    _extracted/
      <snapshot>/
  mvp_score/
    fase1_preparacao.py
    fase2_features.py
    fase3_modelos.py
    fase4_visualizacoes.py
    gerar_pncp_csv.py
    notebook_mvp_score_mei.ipynb
    dados/
    resultados/
```

---

## Metodologia Resumida

1. Baixa contratos do PNCP.
2. Filtra fornecedores pessoa juridica (`tipoPessoa = PJ`).
3. Normaliza CNPJs para 14 digitos.
4. Carrega dados publicos da Receita Federal.
5. Mantem apenas MEIs ativos.
6. Cruza contratos PNCP com MEIs ativos pelo CNPJ.
7. Agrega historico por `CNAE x UF`.
8. Cria features historicas.
9. Compara baseline, regressao logistica e arvore de decisao.
10. Gera score de oportunidade e graficos finais.

---

## Limitacoes

- O score e historico e depende da janela baixada do PNCP.
- Contratos sem CNPJ valido do fornecedor sao descartados.
- Fornecedores pessoa fisica nao entram no cruzamento.
- O resultado depende da qualidade de preenchimento no PNCP e na base CNPJ.
- O MVP modela oportunidade por `CNAE x UF`, nao por empresa individual.
