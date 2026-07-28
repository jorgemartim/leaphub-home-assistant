# Leap Hub Gateway 1.12.48 — startup sem falso connection-refused

- Inicia Connector e OCPP antes do Cloudflare Tunnel.
- Aguarda por uma janela curta até os origins locais responderem ao health check; se não responderem, o supervisor continua normalmente sem travar o App.
- Em shutdown/update planejado, encerra o Tunnel antes de Connector/OCPP, evitando erros de proxy para portas já desligadas.
- Mantém filas, SQLite, fairness, backpressure por usuário e todas as opções da 1.12.47.
- Não limpa /data nem altera credenciais, Charge IDs, transações ou vínculos.
