# Leap Hub Gateway 1.12.83 — dispatch separado da confirmação

Base: Gateway 1.12.82 publicada.

## Objetivo

Preservar os dispatches de ~0,6–0,8 s medidos em lock/unlock/clima e impedir que
um comando de estado continue esperando o polling síncrono de resultado da
`leapmotor-api` ou uma confirmação física antiga.

## Alterações

- ACK-first: lock, unlock, climate_on, climate_off, quick_cool, quick_heat,
  trunk_open, trunk_close, windows_open, windows_close, sunshade_open e sunshade_close.
- porta-malas/janelas/cortina passam a liberar o caminho de envio após ACK, sem
  adicionar retry físico;
- a confirmação física continua no motor de telemetria;
- nova intenção oposta supersede a confirmação pendente anterior da mesma
  família/veículo;
- a telemetria contínua não abre metadados/download remoto de imagem oficial
  enquanto possui a conta; pode reutilizar pacote já em cache;
- a rede automática continua sob o teto curto de 4 s introduzido na 1.12.82.

## Guardrails preservados

- C10 AUTO: payload completo `operate=auto` + `mode=nohotcold`;
- C10 OFF: `ac_switch({"operate":"off"})`;
- climate_off no máximo duas transmissões idênticas;
- sessão/autenticação sem mudança;
- nenhuma terceira transmissão;
- nenhum aumento de polling;
- anúncio imediato Gateway → Site preservado;
- `config.yaml` permanece em 1.12.82 no commit funcional e só é promovido pelo Actions.

## Critério de campo

- lock/unlock/clima devem manter dispatch rápido;
- trunk/windows/sunshade devem deixar de gastar segundos esperando result-poll;
- um comando oposto posterior deve encerrar a confirmação antiga como superseded;
- telemetria não deve voltar a manter a conta dezenas de segundos por rede de imagem.
