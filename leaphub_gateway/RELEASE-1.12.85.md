# Leap Hub Gateway 1.12.85 — handoff rápido para comando manual

Base: Gateway 1.12.84 publicada (`27b8129b26d71cacf0df5ceb2547eafc75803f4d`).

## Evidência de campo

No primeiro `unlock` com o carro em repouso, o worker mediu cerca de 40,6 s em `latência_conta`, mas apenas ~1,03 s de dispatch depois que recebeu a conta. Os comandos seguintes, com a conta livre, voltaram para ~0,6 s.

A causa restante não é o ACK-first nem um método de wake ausente: a telemetria pode entrar nos métodos públicos de leitura da `leapmotor-api==0.3.2`, que possuem retry interno de token. Uma única chamada lógica pode executar leitura, refresh, login e nova leitura antes de devolver o controle ao Gateway.

## Alteração

- a telemetria automática usa uma visão one-shot do mesmo cliente persistente;
- `get_vehicle_list`, `get_vehicle_status` e `get_message_list` chamam as operações privadas one-shot conhecidas da biblioteca fixada;
- a recuperação de sessão continua no `TelemetryEngine`, fora do retry invisível da biblioteca;
- entre etapas o callback `manual_should_yield` continua tendo autoridade para entregar a conta ao comando;
- o cliente do comando não passa pelo adaptador one-shot.

## Guardrails preservados

- ACK-first e dispatch rápido permanecem;
- C10 AUTO/OFF e demais payloads permanecem;
- `climate_off` continua com no máximo duas transmissões idênticas;
- nenhuma terceira transmissão;
- nenhuma segunda sessão concorrente;
- nenhum wake artificial;
- nenhum aumento de polling;
- supersessão e confirmação em segundo plano permanecem;
- anúncio imediato Gateway→Site permanece;
- `config.yaml` permanece em 1.12.84 no commit funcional e só será promovido pelo GitHub Actions após build, smoke test e acesso anônimo ao GHCR.
