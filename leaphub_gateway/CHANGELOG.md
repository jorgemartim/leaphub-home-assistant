## 1.12.53

Distribuição pré-compilada preservada, com publicação em duas fases.

### Renovação de sessão: o alias que faltava

- `_try_refresh_client_session` procurava o método de renovação por `refresh_session`, `refresh_token` e `refresh`. O nome real na `leapmotor-api` é `token_refresh`. Nenhum dos três existia, a renovação nunca acontecia e toda sessão vencida caía no login completo — de 5 a 18 s por conta, medidos em campo.
- `token_refresh` passa a ser o primeiro alias da cadeia. A proteção contra multiplicar chamadas à nuvem continua: deduplicação por identidade da função, parada na primeira resposta conclusiva e classificação única de exceções.
- Se a versão instalada da biblioteca não tiver o método, o comportamento é exatamente o anterior.

### Mantido da 1.12.52

- Entrega com keep-alive ciente da janela do servidor, com repetição imediata em conexão nova e assinatura própria por tentativa.
- Fila em WAL, conexão SQLite por thread, coleta paralela por conta e entrega em thread dedicada.
- Confirmação FAST armada dentro do Gateway ao fim do comando remoto.

### Sem alteração

- Não repete comandos físicos, não altera credenciais, OCPP, MQTT, schema, migrations ou dados existentes.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
