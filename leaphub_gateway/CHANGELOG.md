## 1.12.126

- mantém a distribuição pré-compilada no GHCR oficial e a publicação em duas fases;
- adiciona um pulso HMAC independente a cada 55 segundos para manter o scheduler
  do Site ativo mesmo quando a hospedagem reescreve o cron para `*/15` ou `*/24`;
- isola o pulso em thread e conexão próprias, sem usar SQLite, sessão Leapmotor,
  fila de telemetria, semáforo ou trava de comandos;
- mantém o cron do cPanel como contingência, com os locks autoritativos do Site
  impedindo execução sobreposta;
- preserva integralmente as correções 1.12.117–1.12.125 de conforto, confirmação,
  desembaçador e prioridade de comandos;
- não altera, migra, recalcula nem remove dados coletados.
