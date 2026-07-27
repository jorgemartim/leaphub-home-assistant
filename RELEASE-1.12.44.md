# Leap Hub Gateway 1.12.44 — Persistent Fair Scheduler

## OCPP

- round-robin persistente por usuário para eventos e resultados de comandos;
- resolve starvation quando existem mais usuários com backlog do que o lote de replay;
- cursor avança mesmo quando um usuário entra em backoff, sem bloquear os demais;
- FIFO por wallbox permanece preservado;
- owner_user_id continua sendo somente o identificador numérico interno.

## Compatibilidade

- atualização sobre 1.12.43;
- sem reset das filas SQLite existentes;
- tabela `queue_scheduler_state` é aditiva e criada com `CREATE TABLE IF NOT EXISTS`;
- `config.yaml` permanece em 1.12.43 até a imagem 1.12.44 estar pública no GHCR.
