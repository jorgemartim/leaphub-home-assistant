# Leap Hub Gateway 1.12.13

Baseado integralmente na 1.12.12 mais recente, sem remover API v2, rastreamento, comandos de conforto, OCPP, Cloudflare Tunnel ou configurações existentes.

- Remove a expiração artificial da sessão após 45 minutos e tenta refresh antes de um novo login.
- Coordena telemetria, comandos, teste e sincronização com uma única autenticação por conta.
- Persiste cooldown e aplica backoff progressivo de 5, 10, 20 e 30 minutos após bloqueios consecutivos.
- Impede qualquer chamada à Leapmotor enquanto o cooldown global estiver ativo.
- Deduplica `subscriptions/upsert` idêntico sem fechar sessão, antecipar coleta ou acordar o veículo.
- Reutiliza a sessão da telemetria na sincronização manual e nos comandos compatíveis.
- Corrige oscilações falsas entre `sleep`, `driving` e `parked`, exigindo confirmação antes da troca.
- Usa cadência adaptativa: 20 s dirigindo, 25 s carregando, 90 s estacionado e 10–15 min dormindo.
- Corrige `send_destination` para diferentes assinaturas da biblioteca Leapmotor.
- Sanitiza VIN, conta, Charge ID, e-mail, telefone, IP, MAC, coordenadas, tokens e segredos nos logs.
- Fecha corretamente as conexões SQLite e preserva banco, filas e configurações atuais.
- Mantém os 25 comandos existentes, inclusive aquecimento do volante e dos retrovisores.

Não há migração destrutiva, troca de credenciais ou recadastro obrigatório.
