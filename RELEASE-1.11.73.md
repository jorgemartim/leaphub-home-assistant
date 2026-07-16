# Gateway 1.11.73

- Endpoint para encerrar imediatamente a janela interativa quando a última aba fecha.
- Timeout temporário preserva a sessão nas duas primeiras falhas.
- Nova tentativa interativa em 30, 60 e 120 segundos, sem pausa fixa inicial de cinco minutos.
- Boost de presença não quebra cooldown, autenticação bloqueada ou espera de recuperação.
- Novo login só ocorre após falhas temporárias repetidas ou erro real de autenticação.
