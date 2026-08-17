## 1.12.102

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- corrige a leitura das quatro janelas do C10/B10: o sinal binário dedicado de aberto/fechado passa a ter prioridade sobre o percentual;
- evita que percentuais traseiros `0` mascarem um estado traseiro aberto;
- mantém o percentual apenas como fallback quando o sinal binário não estiver disponível;
- amplia `WINDOW_TELEMETRY_DIAG` para reconhecer somente os IDs numéricos de janela 3727, 3728, 1879, 1880, 1693, 1694, 1695 e 1696;
- preserva comandos físicos, retry, cortina, clima e OCPP sem alterações.
