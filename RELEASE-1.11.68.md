# Leap Hub Gateway 1.11.68

- Recria a sessão e faz login novamente quando a nuvem Leapmotor expira token ou recusa temporariamente a verificação.
- Tenta novamente a lista de veículos em até três sessões novas antes de considerar a credencial inválida.
- Serializa operações por conta para impedir login, teste e sincronização simultâneos com o mesmo usuário.
- Responde 503 para falhas temporárias, sem registrar o caso como erro interno 500.
- A telemetria entra em estado `recovering` e volta sozinha após 15–120 segundos.
- Senha, certificados e tokens continuam criptografados e nunca aparecem nos logs.
