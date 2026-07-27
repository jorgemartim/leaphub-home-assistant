# Leap Hub Gateway 1.12.35 — confirmação rápida e telemetria direcionada

Esta versão retoma a evolução de runtime sem alterar o pipeline GHCR estabilizado na 1.12.34.

## Mudanças

- A janela de confirmação de um comando não fica mais bloqueada pelo `manual_settle`: somente um comando manual realmente pendente bloqueia/preempta a confirmação.
- O período pós-comando continua reservado contra telemetria de fundo, preservando sequências como abrir/fechar e travar/destravar.
- Ao concluir uma ação, o Gateway injeta um hint interno no Event Transport para acordar rapidamente a assinatura da conta/veículo e iniciar a confirmação.
- Hints com veículo passam a acordar somente assinaturas que contenham aquele veículo.
- O Connection Orchestrator expõe métricas de coleta FAST/SLOW, p50/p95 e yields para operação manual.
- MQTT Leapmotor continua desativado até autenticação, tópicos e payloads serem homologados legitimamente.
- Nenhuma migration destrutiva. OCPP, Wallbox e comandos existentes mantêm seus contratos.
