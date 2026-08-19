## 1.12.116

A distribuição continua pré-compilada no GHCR oficial e mantém a
publicação em duas fases.

- WINDOW_TELEMETRY_DIAG passa a incluir um token estável por veículo
  veh_<hash>, sem gravar o identificador bruto do veículo nos logs;
- a deduplicação do diagnóstico de janelas passa a ser isolada por
  veículo, em vez de global;
- a API legada de 3 argumentos de log_window_telemetry_diag permanece
  compatível;
- escala nativa C10 das janelas, fence mecânico, ACK_FIRST e SAFE retry
  permanecem inalterados;
- nenhum payload físico, timeout de atuação, quantidade de transmissões,
  Trips, OCPP, SQLite writer, regra de proximidade ou cadência de confirmação
  foi alterado;
- config.yaml permanece intencionalmente em 1.12.115 até o CI construir,
  testar e confirmar acesso anônimo à imagem GHCR 1.12.116.
