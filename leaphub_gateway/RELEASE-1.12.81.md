# Gateway 1.12.81 — resposta rápida completa

## Objetivo

Recuperar a responsividade observada em Site 1.12.351 + Gateway 1.12.78, preservando o contrato correto de clima introduzido em 1.12.79 e o ACK-first da 1.12.80.

## Climate OFF C10

- continua usando `ac_switch(vin, params={"operate":"off"})`;
- a primeira transmissão não espera mais `_poll_remote_control_result` da leapmotor-api;
- após uma janela curta há somente uma leitura de verificação;
- se essa leitura ainda contradiz o OFF, é permitida uma segunda e última transmissão idempotente exatamente igual;
- a segunda transmissão também é ACK-first;
- não existe terceira transmissão;
- a confirmação final depois da segunda transmissão fica com a telemetria FAST já existente.

## Demais comandos

`lock`, `unlock`, `climate_on`, `quick_cool` e `quick_heat` mantêm o ACK-first da 1.12.80. O payload AUTO continua `operate=auto` + `mode=nohotcold`.

## Atualização imediata do Site

O anúncio assinado de resultado criado na 1.12.78 continua em thread separada e sem retry. A 1.12.81 apenas torna seu sucesso/falha visível em log seguro para diagnóstico; o ciclo normal continua sendo fallback.

## Guardrails

- no máximo duas transmissões para estados climáticos protegidos;
- sem aumento de polling;
- sem terceira transmissão;
- sem mudanças de autenticação, PIN, credenciais ou reuso de sessão;
- Produção não faz parte desta homologação.
