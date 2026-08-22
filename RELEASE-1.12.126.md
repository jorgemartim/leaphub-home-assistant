# Leap Hub Gateway 1.12.126 — scheduler redundante

Adiciona um pulso HMAC independente a cada 55 segundos para manter o scheduler
do Site ativo mesmo quando a hospedagem reescreve o cron do cPanel. O cron
permanece instalado como contingência e os locks do Site evitam sobreposição.

O pulso usa thread e conexão próprias. Ele não abre SQLite, não acessa a nuvem
Leapmotor, não usa fila de telemetria, semáforo ou trava de comandos. Falta de
configuração e Site antigo sem a rota nova são condições não fatais.

Preserva todas as correções da 1.12.125 e anteriores. Não há migration, mudança
de schema, limpeza, exclusão, backfill, recálculo ou alteração de dados.
