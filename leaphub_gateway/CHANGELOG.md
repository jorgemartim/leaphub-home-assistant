## 1.12.50

- Fila de telemetria migra para WAL com `synchronous=NORMAL`, com fallback automático para o comportamento anterior quando o volume não aceita WAL.
- Conexão SQLite reaproveitada por thread; revalidação de permissões e manutenção da fila passam a rodar uma vez por minuto em vez de a cada consulta e a cada volta do laço.
- Coleta paralela por conta com o novo `telemetry_poll_workers`; a mesma conta continua serializada pela trava por conta e pela trava de sessão.
- Entrega ao site em thread dedicada, com timeout de 25s e backoff limitado a 120s.
- Comandos remotos passam a expor `session_wait_ms`, `session_login_ms` e `unaccounted_ms`, fechando a soma das fases com o tempo total.
- Versão da biblioteca `leapmotor-api` resolvida uma vez por processo.
- Padrões novos: `connector_max_parallel` 4, `telemetry_batch_size` 5, `telemetry_poll_workers` 3. Instalações existentes mantêm os valores já salvos.
- Não altera comandos físicos, migrations, schema, filas persistidas, OCPP, credenciais, vínculos ou dados existentes.

## 1.12.49

- Preserva a sessão Leapmotor saudável quando o site repete um `upsert` idêntico após validar as credenciais.
- Evita que uma atualização administrativa da assinatura aguarde uma telemetria em voo ou force autenticação desnecessária.
- Mantém a recuperação explícita quando não existe sessão ativa, quando as credenciais mudam ou quando a assinatura é desativada.
- Não altera comandos físicos, intervalos, filas, SQLite, OCPP, vínculos ou dados existentes.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
