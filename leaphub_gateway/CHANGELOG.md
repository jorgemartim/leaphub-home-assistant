## 1.12.105

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- adiciona `CLIMATE_RAW_PROBE` no mesmo ponto da coleta em que `WINDOW_TELEMETRY_DIAG` já foi comprovado em campo;
- o probe não depende de `climate_state`, `seat_state` ou `mirrors_state`;
- registra `raw_candidates={}` uma vez mesmo quando nenhum sinal é encontrado;
- mantém o diagnóstico tipado da 1.12.104 para comparação;
- nenhum comando físico, retry/resend, janela, cortina ou OCPP foi alterado.
