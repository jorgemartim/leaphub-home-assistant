# Leap Hub Gateway 1.12.122 — confirmação física dos bancos

## Evidência de campo

Os comandos semânticos da 1.12.121 passaram a atuar fisicamente, mas o site
continuava aguardando porque o Gateway não armava confirmação para `seat_heat`
e `seat_ventilation`. Os logs mostraram, na mesma telemetria, os sinais reais:

- `2100`: aquecimento do motorista;
- `2101`: ventilação do motorista;
- `2118`: aquecimento do passageiro;
- `2119`: ventilação do passageiro.

## Correção

- os quatro sinais preenchem apenas campos tipados ausentes; o valor tipado
  continua tendo precedência;
- banco, lado e nível solicitado ficam na janela FAST já existente;
- a confirmação só conclui quando o nível observado é exatamente o esperado;
- nível 0 também é confirmado e representa desligado;
- motorista e passageiro não se sobrescrevem nem são inferidos um pelo outro;
- nenhuma confirmação reenvia o comando físico.

## Segurança e dados

Não há migration, alteração de schema, limpeza, exclusão, backfill ou recálculo.
As leituras usam sinais que já chegavam no mesmo snapshot, sem nova chamada ao
carro. Trips, OCPP, filas, sessões e dados históricos permanecem intactos.

`config.yaml` permanece em 1.12.121 no candidato. O CI promove para 1.12.122
somente depois de testar e confirmar acesso anônimo à imagem exata no GHCR.
