# Leap Hub Gateway 1.11.91

- Separa o aceite da nuvem (`sent`) da confirmação posterior por telemetria.
- O Leap Hub pode liberar imediatamente a interface depois que o comando é realmente enviado.
- A fila continua exclusiva durante a entrega e o próximo comando só avança depois de `sent`, `completed` ou falha.
- Climatização mantém no máximo uma repetição idempotente e executa uma leitura final sem novo envio.
- Se o estado continuar desligado, registra `climate_not_applied_after_retry` para diagnóstico objetivo.
- Preserva a recuperação segura da sessão durante `cert/sync` adicionada na 1.11.90.
