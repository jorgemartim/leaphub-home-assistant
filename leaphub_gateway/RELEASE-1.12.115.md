# Leap Hub Gateway 1.12.115 — Realtime Proximity Safety

Base publicada obrigatória: `89b47eca28f23b64c20f371dc3a9b6a2515c005e` (Gateway 1.12.114).

## Objetivo
Impedir que lock/unlock/trunk_open originados de presença física sejam executados depois que a presença expirou.

## Fail-closed
- `request_origin=mobile_proximity` + `realtime_proximity=true` exige deadline curto;
- conta ocupada: descarta, não enfileira;
- slot global ocupado: descarta, não enfileira;
- cooldown de autenticação: falha sem retry;
- deadline é verificado no worker, TelemetryEngine e imediatamente antes do dispatch no connector;
- request-id inclui origem/deadline na idempotência.

## Congelado
- todos os comandos manuais normais e sua fila;
- payloads físicos;
- ACK_FIRST e SAFE_STATE_RETRY;
- confirmação 5/5/8; Trips 1.12.114; OCPP; maintenance; SQLite writer; escalas C10 e defrost.

## Publicação
O candidato mantém `config.yaml` em 1.12.114. O pacote automático cria worktree/branch isolado, testa e envia somente a branch candidata. Nunca faz merge nem push em main.
