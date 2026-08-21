# Leap Hub Gateway 1.12.125

## Prioridade real após sessão fria

Corrige a fábrica compartilhada do cliente Leapmotor para que o login da
telemetria automática respeite o teto de 4 segundos já definido pelo Gateway.
O piso anterior de 12 segundos podia reter a conta por dezenas de segundos
antes de liberar um comando manual.

O tempo maior do despacho físico permanece isolado no comando, a confirmação
continua autoritativa por telemetria e um gesto continua gerando no máximo um
envio físico.

Não há migration, mudança de schema, limpeza, exclusão, backfill ou recálculo
de dados.
