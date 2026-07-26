# Leap Hub Gateway 1.12.25 — Sentinela experimental isolado

- preserva integralmente a matriz de 25 comandos estáveis da 1.12.24;
- adiciona `sentry_on` e `sentry_off` em uma matriz experimental separada;
- exige `experimental_confirmed` antes de aceitar qualquer comando Sentinela;
- anuncia os dois comandos somente em `experimental_commands`, sem promovê-los a `supported_commands`;
- usa os métodos `sentry_mode_on` / `sentry_mode_off` da biblioteca instalada;
- nunca repete automaticamente o comando Sentinela;
- permite confirmação assíncrona por `telemetry.security.sentry_mode`;
- não altera OCPP, FIFO, Cloudflare, autenticação, limites ou os demais comandos remotos.
