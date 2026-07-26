## 1.12.38

- Impede que uma única conta saudável encerre prematuramente o circuit breaker global enquanto outras contas ainda apresentam timeout, desconexão ou 503.
- A recuperação antecipada exige 30 segundos sem novas falhas e sucesso de duas contas distintas; comandos manuais continuam liberados durante `DEGRADED`.
- Corrige `queue_wait_seconds`: agora mede somente fila da conta + vaga do Connector, sem incluir envio ou confirmação.
- Expõe aliases de latência aditivos (`queue_account`, `queue_connector`, `remote_dispatch` e `post_state_verify`) e informa quando o tempo do resultado remoto está agregado ao despacho pela biblioteca.
- Mantém comandos REST, sessões, retries, telemetria FAST/SLOW, Event Transport passivo, OCPP e distribuição pré-compilada GHCR inalterados.
