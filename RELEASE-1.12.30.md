# Leap Hub Gateway 1.12.30 — Event Transport Foundation

- Adiciona uma camada event-driven independente do polling, pronta para acordar a telemetria por hints legítimos e deduplicados.
- REST permanece ativo como fallback e continua sendo o transporte autenticado de comandos.
- MQTT fica explicitamente `awaiting_homologation`: nenhuma conexão, tópico, credencial ou comando MQTT é inventado antes de homologar o fluxo oficial.
- Hints repetidos na janela curta são coalescidos antes de acordar a telemetria.
- `health/details` passa a informar estratégia de transporte e prontidão para eventos sem expor identificadores.
- Mantém o Connection Orchestrator 1.12.29, sem migrations e sem mudança de OCPP/Wallbox.
