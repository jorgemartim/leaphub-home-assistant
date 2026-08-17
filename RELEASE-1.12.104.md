# Leap Hub Gateway 1.12.104 — diagnóstico raw clima/conforto

A 1.12.103 não gerou `CLIMATE_COMFORT_DIAG` no teste físico do C10.
A 1.12.104 adiciona `raw_candidates` somente para IDs documentados de
clima/conforto do C10/B10, sem registrar GPS, VIN, credenciais ou outros raw.

Nenhum comando físico, retry, janela, cortina ou OCPP foi alterado.
`config.yaml` permanece 1.12.103 até a CI promover 1.12.104.
