## 1.12.55

Distribuição pré-compilada preservada, com publicação em duas fases.

### O precheck do comando remoto ganhou nome e teto

- Um comando medido em campo trouxe `precheck_motor=135718ms` com todas as demais fases somando ~5 s (`dispatch=4199ms`, `handle_command=5219ms`, `arme_confirmacao=1ms`, `nao_atribuido=1ms`). A 1.12.54 nomeou o balde; ele cobre três coisas distintas e não dava para saber qual delas gastava.
- `engine_precheck_ms` passa a ser quebrado em `auth_status_ms` (a checagem de cooldown da conta), `engine_lock_wait_ms` (a espera pela trava global do motor) e `subscription_read_ms` (a leitura da assinatura). As três somam o precheck e aparecem entre colchetes na linha de log.
- A aquisição da trava global no caminho do comando era a única sem limite de espera no arquivo — compare com `self.lock.acquire(timeout=0.15)` e `account_lock.acquire(timeout=...)` usados em outros pontos. Agora ela tem teto de 20 s.
- Estourar o teto vira `ConnectorTemporaryError`, que o servidor já mapeia para HTTP 503 com `temporary: true`. O site trata 503 como falha transitória e mantém o comando na fila. O dispatch acontece bem depois desse ponto, então nenhuma ação física chega ao veículo e nada é repetido: o dono recebe uma resposta em 20 s em vez de olhar a tela por dois minutos.
- A trava é liberada em `finally`. Perdê-la travaria o motor inteiro de forma permanente.

### Mantido da 1.12.54

- `engine_precheck_ms` + `session_wait_ms` + `session_login_ms` + `handle_command_ms` + `confirmation_arm_ms` + não atribuído fecham `remote_execute_ms`.
- `preparo_sessao`, `dispatch`, `verificacao` e `progresso` vivem dentro de `handle_command_ms` e não entram no cálculo de não atribuído. As três fases novas vivem dentro de `engine_precheck_ms` e seguem a mesma regra.
- `token_refresh` como primeiro alias da cadeia de renovação de sessão.
- Entrega com keep-alive ciente da janela do servidor, com repetição imediata em conexão nova e assinatura própria por tentativa.
- Fila em WAL, conexão SQLite por thread, coleta paralela por conta e entrega em thread dedicada.

### Sem alteração

- Não repete comandos físicos, não altera credenciais, OCPP, MQTT, schema, migrations ou dados existentes.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
