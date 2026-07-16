# Gateway 1.11.70

Atualização de segurança da sincronização Leapmotor.

- A telemetria só consulta a nuvem durante uma janela ativada pela presença do usuário no Leap Hub.
- A mesma sessão autenticada é reutilizada durante a janela; não existe novo login em cada ciclo.
- Cada chamada manual ou criação de sessão realiza no máximo uma tentativa de login.
- Reenvios com as mesmas credenciais não removem bloqueio de autenticação nem cooldown.
- Credenciais realmente alteradas liberam uma nova tentativa controlada.
- Falha de autenticação pausa a conta até confirmação explícita.
- Rate limit ativa cooldown padrão de 6 horas.
- Falhas transitórias usam backoff de 5 min, 15 min, 30 min, 1 h, 3 h e 6 h.
- Sessões são encerradas ao expirar a janela, em cooldown, ao trocar credenciais ou ao parar o App.
- Sincronização manual e telemetria usam o mesmo bloqueio por conta, evitando operações simultâneas na mesma sessão Leapmotor.
- Os limites de paralelismo e espera configurados no App são aplicados pelo Connector.
- Leituras idênticas são deduplicadas, com heartbeat periódico para manter a informação de atualização.
- Fila persistente, OCPP, Cloudflare e diagnóstico permanecem preservados.
