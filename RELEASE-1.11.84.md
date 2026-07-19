# Leap Hub Gateway 1.11.84

- Corrige disputa entre o painel e a migração do SQLite.
- Não executa `PRAGMA journal_mode=DELETE` quando o banco já está nesse modo.
- Suspende leituras do painel durante a migração WAL → DELETE.
- Adiciona espera segura para `database is locked`.
- Impede duas instâncias do Connector de usarem a mesma fila.
- Mantém telemetria, tokens e eventos existentes.
