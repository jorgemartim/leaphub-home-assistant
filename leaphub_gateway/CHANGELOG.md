## 1.12.54

Distribuição pré-compilada preservada, com publicação em duas fases.

### As fases do comando remoto fecham a soma

- Dois comandos medidos em campo, um em cold start e outro em regime com sessão reutilizada, deixaram ~90 s de 94 s sem atribuição. Com `espera_sessao`, `login`, `preparo_sessao` e `verificacao` em zero e o dispatch em ~4 s, não havia candidato — e os dois números quase iguais em cenários opostos apontam para tempo fixo, não para disputa de recurso.
- `remote_execute_ms` passa a ser inteiramente atribuível: `engine_precheck_ms` + `session_wait_ms` + `session_login_ms` + `handle_command_ms` + `confirmation_arm_ms` + não atribuído.
- `engine_precheck_ms` cobre da entrada de `execute_command` até a trava de sessão. `handle_command_ms` cobre a chamada inteira ao conector, não só o dispatch. `confirmation_arm_ms` cobre o arme da janela FAST interna, que roda depois do dispatch.
- `progress_ms` quebra `handle_command_ms`: o diário de progresso é chamado várias vezes por comando e nunca teve contador.
- `preparo_sessao`, `dispatch`, `verificacao` e `progresso` vivem dentro de `handle_command_ms` e passam a aparecer entre colchetes na linha de log; somá-los ao total contaria duas vezes, então saíram do cálculo de não atribuído.

### Mantido da 1.12.53

- `token_refresh` como primeiro alias da cadeia de renovação de sessão.
- Entrega com keep-alive ciente da janela do servidor, com repetição imediata em conexão nova e assinatura própria por tentativa.
- Fila em WAL, conexão SQLite por thread, coleta paralela por conta e entrega em thread dedicada.

### Sem alteração

- Esta versão só acrescenta timers e campos de log. Não repete comandos físicos, não altera credenciais, OCPP, MQTT, schema, migrations ou dados existentes.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
