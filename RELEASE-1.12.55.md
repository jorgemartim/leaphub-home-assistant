# Leap Hub Gateway 1.12.55 — o precheck do comando ganhou nome e teto

## Por que esta versão existe

A instrumentação da 1.12.54 fez o trabalho dela. Um comando medido em campo:

```
precheck_motor=135718ms, espera_sessao=0ms, login=0ms, handle_command=5219ms,
arme_confirmacao=1ms, [preparo_sessao=0ms, dispatch=4199ms, verificacao=0ms,
progresso=614ms], nao_atribuido=1ms, execução_remota=140939ms, total=141685ms
```

Os ~90 s que antes ficavam sem atribuição nenhuma agora aparecem inteiros num único lugar: `engine_precheck_ms`, 135,7 s dos 141,6 s. Todo o resto somou cerca de 5 s.

O problema é que `engine_precheck_ms` cobre três coisas diferentes, e não dava para saber qual delas gastava.

## O que mudou

### A fase foi quebrada em três

`engine_precheck_ms` passa a ser detalhado por:

- `auth_status_ms` — a checagem de cooldown da conta (`assert_account_cloud_allowed`)
- `engine_lock_wait_ms` — a espera pela trava global do motor
- `subscription_read_ms` — a leitura da assinatura no SQLite

As três somam o precheck e aparecem entre colchetes na linha de log, no mesmo padrão já usado por `preparo_sessao`/`dispatch`/`verificacao`/`progresso`. Como vivem **dentro** de `engine_precheck_ms`, não entram no cálculo de não atribuído — somá-las contaria duas vezes.

### A trava ganhou teto

No caminho do comando, a trava global era adquirida com `with self.lock`, sem limite de espera. Era a única aquisição sem teto do arquivo: os demais pontos já usam `self.lock.acquire(timeout=0.15)` e `account_lock.acquire(timeout=...)`.

Agora a espera é limitada a 20 s. Estourar o teto levanta `ConnectorTemporaryError`, que o servidor já mapeia para **HTTP 503 com `temporary: true`**. O site trata 503 como falha transitória e mantém o comando na fila.

Isso é seguro porque o dispatch acontece bem depois desse ponto: se o teto estourar, **nenhuma ação física chegou ao veículo** e nada é repetido. A diferença prática é que o dono recebe uma resposta em 20 s em vez de olhar a tela por dois minutos.

A trava é liberada em `finally`. Perdê-la travaria o motor inteiro de forma permanente.

## O que observar depois de atualizar

Na próxima linha de `Comando remoto ... finalizado no worker`, o trecho novo:

```
precheck_motor=%sms [status_conta=%sms, trava_motor=%sms, leitura_assinatura=%sms]
```

- **`trava_motor` alto** — contenção real pela trava global. É a hipótese principal, e aí a correção seguinte é reduzir o escopo do que segura a trava.
- **`leitura_assinatura` alto** — o SQLite é o gargalo, não a trava.
- **`status_conta` alto** — a checagem de cooldown, que é uma leitura curta e seria surpresa.
- **Tudo baixo e o precheck baixo** — o problema não volta, e a causa era ambiental.

## Sem alteração

Não altera `Dockerfile`, credenciais, OCPP, MQTT, schema, migrations ou dados existentes. Não repete comandos físicos. Não muda cadência de telemetria.
