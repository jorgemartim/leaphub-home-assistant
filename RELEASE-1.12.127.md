# Leap Hub Gateway 1.12.127

Release pré-compilada para confirmação mais rápida dos bancos e logs
operacionais mais limpos.

- `seat_heat` e `seat_ventilation` entram na cadência limitada de releitura do
  conforto, sem qualquer repetição automática do comando físico;
- `CLIMATE_RAW_PROBE` e `CLIMATE_COMFORT_DIAG` ficam disponíveis em DEBUG e não
  poluem mais a visualização normal do add-on;
- o pulso redundante do scheduler, a fila persistente, o OCPP, a telemetria e as
  proteções de prioridade permanecem inalterados;
- não há migração nem exclusão de `/data` ou de dados coletados.

A imagem GHCR deve ser publicada e validada anonimamente antes de o
`config.yaml` ser anunciado ao Home Assistant.
