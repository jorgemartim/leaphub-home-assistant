# Leap Hub Gateway 1.12.54 — as fases que faltavam para fechar a conta do comando

## Por que esta versão existe

Dois comandos medidos em campo, em condições opostas:

```
21:15  cold start   login=6620ms  dispatch=6997ms  nao_atribuido=93249ms  total=106869ms
21:21  regime       login=0ms     dispatch=3742ms  nao_atribuido=90539ms  total=94285ms
```

O segundo tem sessão reutilizada, nenhuma autenticação nova e acontece seis minutos depois
do boot. Com `espera_sessao`, `login`, `preparo_sessao` e `verificacao` todos em zero e o
dispatch em ~4 s, **90 de 94 segundos não tinham candidato**. E os dois números quase iguais
em cenários opostos apontam para um tempo fixo, não para disputa de recurso.

Percorrer o código não resolveu: tudo entre a entrada de `execute_command` e a trava de
sessão é leitura de banco, os 31 pontos que pegam o lock global nunca envolvem chamada de
rede, e dentro de `handle_command` as três fases medidas somavam ~4 s. O tempo estava num
trecho sem instrumentação — e continuar adivinhando qual era só produziria mais uma hipótese.

## O que esta versão faz

Fecha a soma. `remote_execute_ms` passa a ser inteiramente atribuível:

```
remote_execute_ms = engine_precheck_ms + session_wait_ms + session_login_ms
                  + handle_command_ms + confirmation_arm_ms + nao_atribuido
```

- **`engine_precheck_ms`** — da entrada de `execute_command` até a trava de sessão
  (`assert_account_cloud_allowed` e a busca da assinatura).
- **`handle_command_ms`** — a chamada inteira ao conector, não só o dispatch.
- **`confirmation_arm_ms`** — o arme da janela FAST interna, que roda depois do dispatch.
- **`progress_ms`** — quebra de `handle_command_ms`: o diário de progresso, chamado várias
  vezes por comando e até agora sem contador.

`preparo_sessao`, `dispatch`, `verificacao` e `progresso` vivem **dentro** de
`handle_command_ms` e aparecem entre colchetes na linha de log. Somá-los ao total contaria
duas vezes — por isso `nao_atribuido` deixou de incluí-los.

## Como ler o resultado

Um comando basta:

- `handle_command=~90000ms` → está no conector; `progresso` e `dispatch` dizem em qual parte.
- `precheck_motor=~90000ms` → está antes da trava de sessão, no motor de telemetria.
- `arme_confirmacao=~90000ms` → é a janela FAST interna.
- `nao_atribuido` continuar alto → sobrou trecho, e aí ele está entre as fases.

## O que não muda

Só timers e campos de log. Nenhuma alteração de comportamento, comando físico, credencial,
vínculo, OCPP, MQTT, schema ou migration. O `token_refresh` da 1.12.53 e o keep-alive da
1.12.52 permanecem como estão.
