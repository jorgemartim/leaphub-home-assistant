## 1.12.37

- Corrige recuperação de sessão quando a Leapmotor responde `remote verify failed: Token is invalid` antes de qualquer ação chegar ao veículo.
- A sessão compartilhada inválida é descartada e o mesmo comando recebe no máximo uma nova autenticação limpa antes do envio; falhas de token após aceite/resultado remoto continuam sem reenvio físico.
- Mantém prioridade manual, telemetria FAST/SLOW, Event Transport, OCPP e distribuição pré-compilada GHCR inalterados.
