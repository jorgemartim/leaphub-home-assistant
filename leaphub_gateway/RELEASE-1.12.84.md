# Leap Hub Gateway 1.12.84 — FAST sem confirmação órfã

Base: Gateway 1.12.83 publicada.

## Objetivo

Preservar os dispatches de ~0,6 s medidos em campo e eliminar duas fontes de ruído: janelas FAST antigas que sobreviviam a um comando posterior já confirmado, e rede secundária executada durante presença interativa.

## Alterações

- `_arm_command_confirmation()` encerra confirmações opostas antigas assim que a nova escrita foi aceita, mesmo quando a nova ação já está `confirmed` e não precisa de nova janela.
- Uma confirmação `quick_cool` antiga, por exemplo, não permanece por 180s depois de `climate_off` confirmado.
- Ciclos interativos e de confirmação não executam a leitura secundária de mensagens; o ciclo de fundo continua autorizado a fazê-la.
- Status do veículo, sessão persistente, ACK-first, anúncio imediato ao Site e regras de retry permanecem.

## Guardrails preservados

- C10 AUTO: `operate=auto` + `mode=nohotcold`;
- C10 OFF: `ac_switch({"operate":"off"})`;
- `climate_off` com no máximo duas transmissões idênticas;
- ACK-first de lock/unlock/clima/porta-malas/janelas/cortina preservado;
- nenhuma terceira transmissão;
- nenhum aumento de polling;
- nenhuma mudança no modelo de autenticação;
- `config.yaml` permanece em 1.12.83 no commit funcional e só é promovido pelo GitHub Actions.
