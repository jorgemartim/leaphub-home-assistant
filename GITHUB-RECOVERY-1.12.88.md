# GitHub Recovery — Gateway 1.12.88

Base: `11f04b4104ca15d58842501e90074a8b86bd20b4`.

- não restaurar `_TelemetryOneShotClient`;
- não criar segundo `LeapmotorApiClient`;
- não usar o mesmo cliente concorrentemente;
- somente status automático vira one-shot;
- no máximo um refresh e uma releitura;
- sem terceira chamada;
- preservar ACK-first, C10 e duas transmissões máximas;
- config.yaml fica 1.12.87 no commit funcional;
- sem force push;
- Site 1.12.358 intocado.
