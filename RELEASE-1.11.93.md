# Leap Hub Gateway 1.11.93

- Corrige o bloqueio temporário de login que era convertido em 30 minutos ou 6 horas.
- Usa o prazo real informado pela Leapmotor com margem curta e máximo de cinco minutos.
- Repara cooldowns e comandos `waiting_auth` inválidos da 1.11.92 durante a atualização.
- Telemetria e comandos continuam usando uma única autenticação por conta.
- A sessão válida limpa imediatamente a proteção temporária.
