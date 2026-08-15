## 1.12.97

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

Hotfix mínimo sobre a 1.12.96 publicada.

- corrige o empacotamento runtime da sonda Official `drivingRecord`;
- instala `official_trip_probe.py` também no `site-packages` como `leaphub_official_trip_probe.py`, no mesmo padrão dos demais módulos internos;
- o motor tenta primeiro o nome runtime e mantém fallback local apenas para testes/desenvolvimento;
- adiciona contrato que falha se Dockerfile e import do motor voltarem a divergir;
- preserva integralmente ACK-first, payloads C10, `climate_off`, retries físicos, 5s → 5s → 8s pós-comando, cadência estrutural de 6s, telemetria, render visual, HMAC, OCPP e Produção.
