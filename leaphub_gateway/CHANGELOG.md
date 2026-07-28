## 1.12.50

Distribuição pré-compilada preservada, com publicação em duas fases.

### Confirmação FAST no Gateway

- Arma a confirmação FAST dentro do Gateway assim que o comando remoto termina, sem depender do próximo ciclo do Worker PHP.
- Reutiliza a sessão que acabou de executar o comando e direciona a coleta ao `remote_id` correto do veículo.
- Torna o `boost` do mesmo `request_id` idempotente: amostras e horário inicial não voltam a zero.
- Preserva o contexto de confirmação durante estados temporários de recuperação.

### Armazenamento da fila

- A fila de telemetria passa a aceitar WAL com `synchronous=NORMAL`, com queda automática para o journal DELETE anterior quando o volume recusa o arquivo `-shm`. O journal deixa de ser imposto pelo código e passa a ser escolha do volume.
- `apparmor.txt` concede mapeamento de memória em `/data` para que o perfil não seja o fator limitante.
- Conexão SQLite reaproveitada por thread, liberada por `close_storage()` em `stop()`.
- Revalidação de permissões e retenção da fila passam a rodar uma vez por minuto em vez de a cada consulta e a cada volta do laço. A expiração de sessão continua acontecendo em todo ciclo.

### Coleta e entrega

- Coleta paralela por conta com o novo `telemetry_poll_workers`; a mesma conta continua serializada pela trava por conta e pela trava de sessão.
- Entrega ao site em thread dedicada, com timeout de 25s e backoff limitado a 120s.

### Diagnóstico

- Comandos remotos passam a expor `session_wait_ms`, `session_login_ms` e `unaccounted_ms`, fechando a soma das fases com o tempo total.
- Versão da biblioteca `leapmotor-api` resolvida uma vez por processo.

### Padrões e compatibilidade

- Padrões novos: `connector_max_parallel` 4, `telemetry_batch_size` 5, `telemetry_poll_workers` 3. Instalações existentes mantêm os valores já salvos.
- Não repete comandos físicos, não altera credenciais, OCPP, MQTT, schema ou dados existentes.
