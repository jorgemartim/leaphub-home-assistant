# Leap Hub Gateway 1.12.49 — upsert sem derrubar sessão saudável

- Deduplica a confirmação repetida de credenciais quando a configuração e a sessão continuam válidas.
- Evita espera desnecessária na trava de sessão e nova autenticação após sincronizações administrativas.
- Preserva o caminho de recuperação quando não há sessão ativa.
- Não altera comandos físicos, OCPP, SQLite, credenciais, Charge IDs, transações ou vínculos.
