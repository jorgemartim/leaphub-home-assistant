# Leap Hub Gateway 1.12.00

## Cancelamento protegido

- Novo endpoint assinado `/v1/vehicles/command/cancel`.
- Cancela apenas solicitações ainda em fila, aguardando conta, vaga ou autenticação.
- Ações que já começaram a ser enviadas ao veículo não são interrompidas nem marcadas como canceladas.
- O cancelamento remove timers de retomada e permanece registrado no diário de comandos.
