# Leap Hub Gateway 1.12.102

## Correção das quatro janelas

A 1.12.101 mostrou no veículo real que, após abrir as quatro janelas, os estados
dianteiros mudavam para true enquanto os percentuais traseiros permaneciam em 0.0.
A lógica anterior priorizava o percentual e, por isso, mascarava os sinais binários
traseiros.

A 1.12.102 usa o sinal binário dedicado de aberto/fechado como fonte principal e
o percentual apenas como fallback.

## Diagnóstico

O diagnóstico passa a aceitar somente os oito IDs de janela documentados na
leapmotor-api v0.3.2: 3727, 3728, 1879, 1880, 1693, 1694, 1695 e 1696.
Nenhum payload bruto completo é registrado.

## Preservado

- config.yaml permanece 1.12.101 até a CI publicar/promover 1.12.102;
- nenhum resend/retry novo;
- nenhum comando físico de janela foi alterado;
- cortina e OCPP não foram alterados.
