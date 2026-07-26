# Leap Hub Gateway 1.12.36 — diagnóstico de latência e wake-up coalescido

Esta versão não altera o pipeline GHCR e não muda contratos físicos dos comandos. O foco é medir o caminho real de cada ação e reduzir wake-ups redundantes.

## Alterações

- Latência de comando decomposta em espera da conta, vaga do Connector, preparo/reuso de sessão, dispatch/result remoto e verificação.
- O `ConnectionOrchestrator` calcula p95 por fase e informa `primary_bottleneck`, sem PII.
- O `EventTransport` mantém a deduplicação de eventos e acrescenta coalescência de wake-up por destino durante 1,5 s. Eventos distintos continuam contabilizados; apenas o wake redundante é evitado.
- Logs de conclusão exibem `preparo_sessao`, `dispatch` e `verificacao`, facilitando localizar onde o tempo está sendo gasto.
- REST continua sendo o transporte funcional de comandos e telemetria; MQTT permanece aguardando homologação.

## Compatibilidade

- Sem alteração destrutiva de configuração.
- Sem migration de banco.
- OCPP, Wallbox, Cloudflare e contratos dos comandos existentes preservados.
- Imagem pré-compilada continua em `ghcr.io/jorgemartim/leaphub-gateway:<versão>`.
