# Regras de Negocio do MVP (Oficiais)

## Target de Classificacao

- Unidade de analise: combinacao `CNAE x UF`.
- Variavel de interesse: `count_contratos` (quantidade historica de contratos no grupo).
- Regra oficial:
  - `target = 1` se `count_contratos >= P75(count_contratos)`
  - `target = 0` caso contrario

Essa regra substitui fallback adaptativo para garantir consistencia entre execucoes e comparabilidade de resultados.

## Justificativa

- `P75` representa o quartil superior de desempenho historico.
- O score passa a buscar perfis de oportunidade no segmento de maior recorrencia de contratacao.
