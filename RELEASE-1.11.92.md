# Leap Hub Gateway 1.11.92

- Mantém comandos na fila quando a Leapmotor bloqueia temporariamente novos logins.
- Interpreta o prazo `try again in N minutes` e agenda uma única retomada automática.
- Telemetria e comandos respeitam o mesmo cooldown por conta.
- Diferencia bloqueio temporário de autenticação de senha realmente recusada.
- Preserva as correções de `sent`, fila protegida e diagnóstico de climatização das versões anteriores.
