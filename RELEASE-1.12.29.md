# Leap Hub Gateway 1.12.29 — Connection Orchestrator

- Circuit breaker por ambiente reduz somente telemetria automática quando múltiplas contas indicam instabilidade da nuvem Leapmotor; comandos manuais continuam permitidos.
- Telemetria dividida em perfil FAST (estado essencial) e SLOW (mensagens/imagem oficial), preservando a última imagem no site e evitando trabalho secundário em toda leitura.
- Deduplicações de assinatura passam a ser contabilizadas no diagnóstico sem abrir chamadas adicionais à nuvem.
- Comandos remotos registram latência separada de espera da conta, vaga do Connector e execução remota; métricas agregadas p50/p95 ficam no health/details sem PII.
- Nenhuma opção nova obrigatória, migration, retry físico ou alteração no OCPP/Wallbox.
