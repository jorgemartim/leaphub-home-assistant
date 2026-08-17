# Leap Hub Gateway 1.12.107 — correção do desembaçador dianteiro

## Evidência de campo

No C10 testado, o MAX manual do para-brisa publicou `signal.1945=2` e
`windshield_defrost=true`. O comando remoto anterior retornou sucesso da
biblioteca, aplicou a assinatura HOT/32 °C/fan 7, mas manteve `signal.1945=0` e
`windshield_defrost=false`.

## Causa

`leapmotor-api==0.3.2` monta o preset interno de `windshield_defrost` com
`wshld=1`. A implementação de payloads verificados do protocolo Leapmotor usa
`wshld=2` para WINDSHIELD DEFROST; `quick_heat` permanece em `wshld=1`.

## Correção

Somente `windshield_defrost` passa a fornecer explicitamente ao método da
biblioteca:

- circle=in;
- mode=hot;
- operate=manual;
- position=all;
- temperature=32;
- windlevel=7;
- wshld=2.

Não há retry/resend adicional. `quick_heat`, AUTO/OFF, janelas, cortina, capô e
OCPP não são alterados. `config.yaml` permanece 1.12.106 no commit funcional e
só pode ser promovido pelo fluxo normal de CI/GHCR.
