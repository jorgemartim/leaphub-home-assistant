# Leap Hub Gateway 1.12.12

- Distingue cooldown curto de autenticação de um limite geral de requisições.
- Persiste o horário de cada tentativa de login e impede repetição automática por reinício ou múltiplas ativações.
- Depois de duas recusas temporárias, amplia a espera para cinco minutos antes de uma única nova tentativa.
- Mantém credenciais criptografadas e retoma automaticamente quando a janela segura terminar.
- Publica motivo do cooldown e horários de autenticação no diagnóstico administrativo.
- Não altera comandos físicos, OCPP ou a telemetria já recebida.
