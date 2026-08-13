# Gateway 1.12.80

## Objetivo

Recuperar a resposta rápida observada antes da 1.12.79 sem reverter o payload correto do C10.

## Mudança

A `leapmotor-api==0.3.2` escreve o comando remoto e depois espera, de forma síncrona, o resultado de `remoteCtlId`. Para `lock`, `unlock`, `climate_on`, `quick_cool` e `quick_heat`, o Gateway agora retorna após a escrita remota e deixa a confirmação física para a telemetria FAST já existente.

`climate_off` permanece no caminho anterior nesta rodada para preservar o desligamento e o retry protegido já homologados.

## Segurança

- allow-list explícita de comandos ACK-first;
- override do polling apenas no objeto de sessão já protegido pela trava de operação;
- restauração em `finally`;
- ACK não é rotulado como confirmação física;
- `remote_result_status=ack_only`;
- `confirmation_pending=true`;
- sem terceira transmissão;
- sem aumento de polling.
