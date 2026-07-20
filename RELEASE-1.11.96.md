# Leap Hub Gateway 1.11.96

- Fila e trava por conta Leapmotor, permitindo usuários independentes em paralelo.
- Comandos manuais passam na frente de novas leituras automáticas quando o Connector está cheio.
- O limite `connector_max_parallel` continua sendo uma proteção global, não uma fila única de usuário.
- Compatibilidade com instalações que ainda possuem `telemetry_rate_limit_cooldown_seconds: 21600`; o motor reduz internamente para o limite seguro.
