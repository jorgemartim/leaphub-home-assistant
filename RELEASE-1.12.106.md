# Leap Hub Gateway 1.12.106 — hotfix de telemetria contínua

## Evidência

Antes do restart para 1.12.103, o log registrava `collection_total` normalmente.
Após 1.12.103/1.12.104/1.12.105, as coletas passaram a chegar a
`vehicle_list_request` e aos diagnósticos intermediários, porém sem
`collection_total`.

Na 1.12.105 o padrão ficou explícito: `CLIMATE_RAW_PROBE` aparece, mas a coleta
não chega ao final. No Site, todos os carros ficam com evento antigo e a fila
pode mostrar 0 pendências porque o evento falha antes de ser enfileirado.

## Causa confirmada no código

`serialize_vehicle()` executava:

`log_climate_comfort_diag(climate_state, seat_state, mirrors_state, ...)`

antes de criar `seat_state` e antes de criar `climate_state`.

## Correção

A 1.12.106 remove a chamada do ponto incorreto e a reinsere somente depois da
construção de `seat_state` e `climate_state`.

Não altera comandos físicos, retry, janelas, cortina, OCPP ou HMAC.
`config.yaml` permanece 1.12.105 no commit funcional até promoção pela CI.
