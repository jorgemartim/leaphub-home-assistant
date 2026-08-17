# Leap Hub Gateway 1.12.108 — agenda FAST sem corrida pós-comando

## Sintoma

A janela de confirmação já publica 5/5/8 segundos, mas em campo a próxima
consulta podia aparecer perto de 50 segundos depois de um comando aceito.

## Causa 1 — snapshot antigo sobrescrevia o arme novo

O poll automático lê uma linha SQLite e usa esse snapshot durante a chamada à
nuvem. A trava da conta é liberada antes do processamento local final. Nesse
intervalo um comando manual pode ser aceito e armar uma nova confirmação com
`next_run_at` imediato. Ao terminar, o poll antigo gravava novamente o seu
`next_run_at` normal e podia também sobrescrever o `command_poll_count` recém
zerado.

## Causa 2 — recovery anterior sobrevivia ao comando aceito

Uma falha temporária de telemetria pode gravar `recovering/error` com 45/120 s de
espera. Depois que a conta é liberada, um comando manual pode funcionar. O arme
da confirmação tratava aquele recovery antigo como proteção absoluta e não
puxava a primeira leitura para a janela FAST.

## Correção segura

- a finalização do poll reconcilia a agenda viva na mesma transação SQLite;
- somente uma confirmação pendente mais nova que o snapshot pode preservar a
  agenda urgente e o contador novo;
- cooldown e auth_required criados depois do snapshot vencem a finalização antiga;
- somente o perfil `command` pode cortar `recovering/error`; presença interativa
  e fundo continuam respeitando esse backoff;
- cooldown, autenticação e rate-limit continuam sem bypass.

## Escopo congelado

Nenhum payload físico é modificado. `SAFE_STATE_RETRY_COMMANDS` continua somente
`climate_on`/`climate_off`; não há retry/resend novo. Windshield defrost continua
`wshld=2`. Janelas, cortina, capô e OCPP não mudam. A cadência nominal pós-comando
permanece 5/5/8 e os backoffs continuam 8/15/25/40/60/90.

`config.yaml` permanece em 1.12.107 no commit funcional e só pode ser promovido
pelo fluxo normal de CI/GHCR depois do merge.
