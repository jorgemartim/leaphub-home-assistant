## 1.12.51

Distribuição pré-compilada preservada, com publicação em duas fases.

### Correção do build da 1.12.50

- O autoteste da imagem deixa de exigir um journal fixo. O contrato passa a ser: WAL quando o volume aceita, DELETE quando não aceita, e o motor precisa reportar o modo que realmente ficou valendo. Foi essa asserção fixa que reprovou o build assim que o volume da imagem aceitou WAL.
- O autoteste fecha a conexão de sondagem do SQLite. `sqlite3.connect` como context manager encerra a transação, não a conexão, e o arquivo da fila ficava aberto até o processo sair.

### Entrega ao site

- A conexão TLS com o site passa a ser reaproveitada entre lotes. Com o lote menor recomendado para hospedagem compartilhada, o handshake por lote passou a custar mais que a própria entrega.
- Qualquer erro de transporte descarta a conexão antes de devolvê-la ao uso, para que nenhuma resposta seja lida fora de ordem.

### Observabilidade

- `/health/details` passa a expor `collection`: coletas paralelas configuradas, quantas estão em voo, se os workers estão saturados, se a conexão de entrega está sendo reaproveitada e qual journal ficou valendo.

### Mantido da 1.12.50

- Confirmação FAST armada dentro do Gateway ao fim do comando remoto, com `boost` idempotente por `request_id`.
- Fila em WAL com `synchronous=NORMAL` e queda automática para DELETE, conexão SQLite por thread, retenção com throttle e expiração de sessão em todo ciclo.
- Coleta paralela por conta, entrega em thread dedicada, backoff de entrega limitado a 120s.
- `session_wait_ms`, `session_login_ms` e `unaccounted_ms` nos comandos remotos.

### Sem alteração

- Não repete comandos físicos, não altera credenciais, OCPP, MQTT, schema, migrations ou dados existentes.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
