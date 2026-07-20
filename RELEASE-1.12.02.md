# Leap Hub Gateway 1.12.02

- Chaves HMAC separadas para Beta e Produção.
- Cache persistente de rota por Charge ID.
- Promoção para Produção aplicada por override explícito e reconexão controlada.
- Fila SQLite persistente para eventos OCPP tolerantes a indisponibilidade do site.
- Heartbeat, StatusNotification e MeterValues recebem resposta rápida e são reenviados.
- Respostas HTML/524 continuam resumidas no log.
- O serviço inicia quando Beta ou Produção estiver habilitado.
