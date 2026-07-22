# Leap Hub Gateway 1.12.15

Atualização de conexão e proteção de autenticação, construída sobre a 1.12.14 sem remover endpoints, comandos, OCPP ou configurações.

## Leapmotor e comandos

- preserva corretamente backoffs de autenticação de 5, 10, 20 e 30 minutos no diário de comandos;
- impede que um POST idempotente retome o comando enquanto o cooldown global ainda estiver ativo;
- retoma o comando somente depois da liberação confirmada pelo coordenador da conta;
- evita chamar vários aliases de refresh após timeout, rate limit ou bloqueio de login;
- mantém uma única tentativa lógica de recuperação da sessão.

## Leap Hub e Gateway

- responde em HTTP/1.1 persistente e deixa de forçar `Connection: close`;
- permite reutilização segura da conexão pelo Cloudflare Tunnel;
- preserva HMAC, nonce, API v2, limites de corpo e rastreamento de requisições.

## Compatibilidade

- mesmos 25 comandos remotos;
- mesmos endpoints da API v2;
- mesmas portas OCPP e Connector;
- nenhum recadastro de conta, veículo ou wallbox;
- banco SQLite atualizado de forma compatível e sem apagar dados.
