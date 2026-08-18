# Leap Hub Gateway 1.12.114 — Trip Telemetry Quality

Base publicada obrigatoria: `66e7a0ffb3ec0bf78bb2fca4dd4cd0f81867c53f` (Gateway 1.12.113).

## Objetivo
Melhorar Trips sem alterar comandos fisicos ou substituir contratos que ja funcionam.

## Alteracoes
- `speed_kmh` e `odometer_km` legados permanecem intactos;
- adiciona `raw_vehicle_speed_kmh` a partir do signal 1319;
- adiciona `raw_odometer_km` a partir do signal 1318;
- adiciona `vehicle_timestamp` vindo do quadro do veiculo;
- memoriza/persiste sinais de hemisferio por assinatura+veiculo;
- um positivo isolado contrario ao hemisferio lembrado nao vira salto geografico;
- mudanca real de hemisferio e aceita perto do meridiano/equador ou apos 10 confirmacoes;
- durante conducao, agenda de fundo usa 8s;
- quadros repetidos recuam 8 -> 8 -> 10 -> 12 -> ate 20s/limite ativo;
- quando um quadro novo chega, volta imediatamente a 8s.

## Congelado
- comando/ACK e lane por conta;
- `COMMAND_POST_DISPATCH_EARLY_CADENCE = (5, 5, 8)`;
- `SAFE_STATE_RETRY_COMMANDS = {climate_on, climate_off}`;
- janelas/cortina continuam fora de ACK-first;
- C10 continua com escrita de janelas 0-10 comprovada em campo;
- defrost ON/OFF continua 2/0;
- OCPP, auth/cooldown, maintenance e SQLite writer nao mudam.

## Publicacao
Este candidato nao altera `config.yaml`. Publicacao continua pelo fluxo normal de CI/GHCR depois de merge/revisao.
