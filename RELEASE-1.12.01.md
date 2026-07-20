# Gateway 1.12.01

- Um único serviço OCPP em ocpp-wallbox.leaphub.com.br na porta 8092.
- Produção primeiro, Beta como fallback pelo mesmo Charge ID.
- Status com timeout curto e backoff; HTML/524 não é despejado no log.
- Polling adaptativo de comandos.
