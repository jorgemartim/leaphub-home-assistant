## 1.12.106

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- corrige regressão de telemetria introduzida na 1.12.103;
- `CLIMATE_COMFORT_DIAG` não usa mais `climate_state`/`seat_state` antes da criação dessas variáveis;
- restaura a conclusão de `serialize_vehicle()`, `collection_total` e o caminho de fila/entrega ao Site;
- preserva `CLIMATE_RAW_PROBE` da 1.12.105;
- nenhum comando físico, retry/resend, janela, cortina ou OCPP foi alterado.
