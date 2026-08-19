## 1.12.115

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- comandos assinados de `mobile_proximity` (`lock`, `unlock`, `trunk_open`) passam a ser efêmeros e fail-closed;
- presença não espera conta ocupada nem vaga do Connector: é descartada sem envio;
- cooldown/login não agenda retry para presença;
- deadline é conferido no Site/Gateway e novamente imediatamente antes da escrita remota;
- comandos normais continuam com a fila manual existente e os mesmos timeouts;
- payload físico, ACK_FIRST, SAFE retry, Trips 1.12.114, OCPP, SQLite writer e cadências permanecem congelados;
- `config.yaml` permanece em 1.12.114 até publicação normal por CI/GHCR.
