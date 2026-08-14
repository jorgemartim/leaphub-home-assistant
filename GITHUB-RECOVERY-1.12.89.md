# GitHub Recovery — Gateway 1.12.89

Base publicada: `0627408df89ff5939c1de7640340fec582e2e95b`.

Guardrails:
- manter Site 1.12.358 intocado;
- manter um único `LeapmotorApiClient` por sessão;
- não reintroduzir `_TelemetryOneShotClient`;
- não usar wrappers públicos de lista/status/mensagens para cliente real na telemetria;
- no máximo um refresh e uma releitura por leitura automática expirada;
- comando manual vence antes de refresh/retry quando chega durante uma leitura;
- preservar ACK-first, C10 e `climate_off` no máximo duas transmissões;
- `config.yaml` fica 1.12.88 no commit funcional;
- sem force push e sem `git add .`.
