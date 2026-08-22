## 1.12.127

- inclui aquecimento e ventilação dos bancos na cadência rápida e limitada de
  confirmação, sem reenviar comandos físicos;
- mantém os diagnósticos brutos `CLIMATE_RAW_PROBE` e `CLIMATE_COMFORT_DIAG`
  disponíveis em DEBUG, retirando o ruído do log operacional padrão;
- preserva o pulso redundante do scheduler, fila persistente, telemetria,
  comandos, banco SQLite, distribuição pré-compilada no GHCR e todo o histórico
  coletado.
