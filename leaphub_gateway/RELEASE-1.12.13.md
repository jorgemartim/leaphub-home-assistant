# Leap Hub Gateway 1.12.13

- Remove a expiração artificial de 45 minutos e reutiliza a sessão enquanto a Leapmotor a aceitar.
- Tenta renovação/refresh da sessão antes de iniciar novo login.
- Coordena uma única autenticação por conta entre telemetria, sincronização, recuperação e comandos.
- Persiste cooldown e origem da autenticação no SQLite, inclusive após reiniciar o add-on.
- Aplica backoff progressivo de 5, 10, 20 e 30 minutos após bloqueios consecutivos.
- Impede toda nova autenticação durante o cooldown e libera no máximo uma tentativa protegida ao final da janela.
- Transforma upsert idêntico em operação local: não muda a agenda, não estende presença, não fecha sessão e não acorda a nuvem.
- Corrige a interpretação de READY/ignição como condução e exige confirmação antes de alternar sleep ↔ driving.
- Usa 20 s dirigindo, 25 s carregando, 90 s estacionado e 10–15 min dormindo.
- Corrige `send_destination` para assinaturas antigas e novas da biblioteca Leapmotor.
- Fecha conexões SQLite curtas corretamente para reduzir contenção e descritores abertos.
- Pseudonimiza VIN, conta, Charge ID, MAC, IP, coordenadas, e-mail, rastreamento e segredos em todos os logs e diagnósticos.
- Mantém endpoints, configuração, OCPP, filas, dados persistidos e contratos atuais sem migração destrutiva.
