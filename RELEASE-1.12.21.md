# Leap Hub Gateway 1.12.21

- Encerra de forma limpa as respostas privadas de `/health/details` e `/v1/telemetry/status`.
- Elimina falsos timeouts registrados 15 segundos depois de uma resposta `200`.
- Mantém coerentes o resultado e o diário de comandos enquanto a confirmação da telemetria estiver pendente.
- Não altera credenciais, assinaturas, fila SQLite, OCPP ou configurações existentes.
