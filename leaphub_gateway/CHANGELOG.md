## 1.12.52

Distribuição pré-compilada preservada, com publicação em duas fases.

### Entrega ao site: a outra metade do keep-alive

- A conexão TLS reaproveitada da 1.12.51 não verificava se o socket continuava aberto. `http.client` só descobre isso no `getresponse()`, depois de já ter escrito a requisição inteira. Como a hospedagem compartilhada fecha a conexão ociosa em poucos segundos e os lotes saem a cada 20-120s, praticamente toda entrega reaproveitada falhava com `Remote end closed connection without response` — sem o PHP do site chegar a executar — e o lote inteiro voltava para o backoff.
- A conexão ociosa além da janela de keep-alive é descartada antes do envio. O padrão é conservador (5s) e passa a seguir o `Keep-Alive: timeout=N` quando o servidor informa um.
- Uma falha de transporte sobre conexão reaproveitada ganha uma tentativa imediata em conexão nova. É seguro: ali o servidor comprovadamente não respondeu, e a ingestão do site é idempotente pelo `event_id`.
- Cada tentativa recebe assinatura própria. O site trata o nonce como uso único, então repetir com o cabeçalho anterior seria recusado como requisição repetida.

### Efeito

- A telemetria volta a chegar no primeiro envio. Como a reconciliação de comandos roda dentro da ingestão do site, a confirmação de `lock`/`unlock` deixa de esperar ciclos inteiros de backoff.
- O ganho da 1.12.51 é preservado: dentro de uma rajada de lotes a conexão continua sendo reaproveitada, que é justamente quando o handshake pesava.

### Mantido da 1.12.51

- Fila em WAL com `synchronous=NORMAL` e queda automática para DELETE, conexão SQLite por thread, retenção com throttle e expiração de sessão em todo ciclo.
- Coleta paralela por conta, entrega em thread dedicada, backoff de entrega limitado a 120s.
- Confirmação FAST armada dentro do Gateway ao fim do comando remoto, com `boost` idempotente por `request_id`.
- `/health/details` expondo `collection`, incluindo se a conexão de entrega está sendo reaproveitada e qual journal ficou valendo.
- `session_wait_ms`, `session_login_ms` e `unaccounted_ms` nos comandos remotos.

### Sem alteração

- Não repete comandos físicos, não altera credenciais, OCPP, MQTT, schema, migrations ou dados existentes.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
