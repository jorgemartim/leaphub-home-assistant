# GitHub Recovery — Gateway 1.12.120

Base publicada obrigatória: `821b15d` (Gateway 1.12.119 publicado).

Escopo: manter a cadência FAST histórica para todas as famílias e selecionar
uma escada limitada 5/5/8/10/10/12/... apenas quando existir confirmação
pendente de clima, desembaçador, volante ou retrovisores.

Não alterar despacho, payload, retry, confirmação física, prazo, banco, fila,
Trips, OCPP ou dados coletados. Não executar migration, limpeza, exclusão ou
recálculo.

`config.yaml` permanece `1.12.119` no candidato. A promoção para `1.12.120`
depende do workflow verde, smoke test e confirmação pública do GHCR.
