# Leap Hub Gateway 1.12.123 — OFF real do desembaçador

## Problema confirmado em campo

O pacote OFF removia `wshld`, porém também reenviava `mode=hot`, temperatura
32 °C e ventilador 7. O para-brisa desligava, mas a cabine voltava a aquecer.

## Correção

- ON continua usando o pacote homologado `wshld=2`;
- OFF usa um único cmd 170 com `operate=off` e `wshld=0`;
- não existe segundo comando, repetição física nem alteração automática de
  temperatura ou ventilação;
- a mesma confirmação FAST por telemetria permanece obrigatória.

## Segurança e dados

Não há migration, limpeza, exclusão, backfill ou recálculo. Banco local,
telemetria, viagens, carregamentos, OCPP, filas e histórico são preservados.

`config.yaml` permanece em 1.12.122 no candidato. O CI promove para 1.12.123
somente após testes e publicação da imagem exata no GHCR.
