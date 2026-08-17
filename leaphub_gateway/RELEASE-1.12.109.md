# Leap Hub Gateway 1.12.109 — defrost OFF + Prepare FAST

## Desembaçador
ON permanece `windshield_defrost` sem parâmetro (ou `enabled=true`) com `wshld=2`. OFF usa o MESMO comando com `enabled=false` e muda somente para `wshld=0`.
Sem retry/resend novo.

## Preparar
`prepare_car` entra na janela FAST e confirma clima ligado + modo + temperatura
+ ventilação na mesma amostra nova.

## Arme
Quando a confirmação está pendente, `boost()` já registra e supersede na mesma
passagem. A passagem redundante anterior foi removida. `CONFIRM_ARM_DIAG` loga
`boost`/`supersede` acima de 750 ms.

## Congelado
5/5/8; 8/15/25/40/60/90; SAFE retry somente climate_on/off; ON wshld=2;
windows/sunshade/hood/OCPP sem alteração; config.yaml não promovido.
