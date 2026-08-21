# 1.12.124

## Resposta rápida dos controles de conforto

O envio físico de bancos e desembacador era concluído pela nuvem, mas a
biblioteca continuava consultando o resultado internamente antes de devolver o
ACK ao Site. Em campo, o desembacador levou 19,25 segundos só nessa etapa.

Esta versão adia exclusivamente essa consulta interna e devolve o ACK após o
primeiro despacho. A confirmação física por telemetria continua obrigatória e
ocorre em segundo plano.

## Segurança e dados

- um gesto produz exatamente um despacho físico;
- bancos e desembacador não entram em retry automático;
- o OFF do desembacador continua sendo apenas `operate=off` + `wshld=0`;
- não há migration, limpeza, backfill, recálculo nem exclusão de dados.

`config.yaml` permanece em 1.12.123 no candidato. O CI promove para 1.12.124
somente após testes, imagem publicada e pull anônimo confirmado no GHCR.
