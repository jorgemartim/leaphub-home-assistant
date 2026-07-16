# Leap Hub Gateway 1.11.75

- Corrige o erro `name 'secrets' is not defined` no status OCPP.
- Preserva a sessão Leapmotor durante transições rápidas entre páginas.
- Evita novo login quando uma aba fecha e outra página do Leap Hub abre em seguida.
- Aplica espera conservadora para `Information verification failed`.
- Reduz ruído de `boost` e `release` no log normal.
- Limita repetição de erros idênticos da API de status a uma vez a cada cinco minutos.
