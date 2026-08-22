# 1.12.126

## Scheduler resiliente à hospedagem

Um worker isolado envia ao Site um POST HMAC mínimo a cada 55 segundos. Assim,
as automações continuam cadenciadas quando a hospedagem substitui o cron de um
minuto por `*/15` ou `*/24`.

O relógio redundante não toca em sessão Leapmotor, SQLite, fila de entrega,
semáforo ou trava de conta. O cron do cPanel permanece como contingência e os
locks autoritativos do Site impedem ciclos concorrentes.

## Segurança e dados

- nenhum comando físico ou retry foi adicionado;
- erros, timeout, configuração ausente e rota 404 são não fatais;
- nenhuma migration, limpeza, exclusão, backfill ou recálculo é executado;
- `config.yaml` permanece em 1.12.125 até o CI publicar e validar a imagem
  1.12.126 anonimamente no GHCR.
