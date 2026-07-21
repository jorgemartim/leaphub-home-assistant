# Leap Hub Gateway 1.12.07

- Corrige a corrida entre telemetria automática e comando manual durante a criação de uma sessão Leapmotor.
- A telemetria verifica a prioridade manual antes de criar o cliente e antes de efetuar login.
- Comandos em cooldown informam explicitamente que devem ser retomados com o mesmo request_id após `retry_at`.
- A retomada é idempotente: o timer interno e a recuperação pelo Leap Hub não duplicam o comando.
- Mantém a contenção de requisições e a compatibilidade de configuração da 1.12.06.
