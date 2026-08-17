# Leap Hub Gateway 1.12.105 — probe de clima no ponto comprovado

A 1.12.104 foi confirmada em runtime pelo `/health` (`version=1.12.104`).
No mesmo log, `WINDOW_TELEMETRY_DIAG` apareceu depois do restart, mas nenhuma
linha `CLIMATE_COMFORT_DIAG` apareceu após o teste físico.

A 1.12.105 adiciona `CLIMATE_RAW_PROBE` imediatamente depois do
`WINDOW_TELEMETRY_DIAG`, usando o mesmo `status.raw`. Isso remove a dependência
de qualquer construção posterior de estado tipado.

Mesmo sem sinal, deve aparecer uma vez:
`CLIMATE_RAW_PROBE raw_candidates={}`

Nenhum comando físico, retry/resend, janela, cortina ou OCPP foi alterado.
`config.yaml` permanece 1.12.104 até promoção automática pela CI.
