# Leap Hub Gateway 1.12.25 — Sentry Capability Probe

## Objetivo
Permitir testar de forma controlada se C10/B10 realmente aceitam o Modo Sentinela pela autenticação normal da conta, sem alterar região, VIN, certificado ou qualquer autorização da Leapmotor.

## Alterações
- Inclui `sentry_on` → `sentry_mode_on` e `sentry_off` → `sentry_mode_off`.
- Os dois comandos permanecem experimentais e separados de `supported_commands`.
- A execução exige `parameters.experimental_confirmed = true`.
- Após o envio, o Gateway consulta `status.security.sentry_mode` por até 30 segundos e registra se o estado foi confirmado, permaneceu pendente ou não é exposto pelo veículo.
- Não existe repetição automática do Sentinela durante a confirmação.
- Nenhuma alteração em credenciais, certificados, VIN, região, OCPP ou portas.

## Como interpretar o primeiro teste
- `final_outcome=confirmed`: o veículo aceitou e o estado foi observado.
- `confirmation_pending` + `sentry_state_pending`: a nuvem aceitou, mas a leitura ainda não confirmou a mudança.
- `confirmation_pending` + `sentry_state_unavailable`: o comando foi aceito, porém o estado `sentry_mode` não veio na telemetria.
- erro retornado pela biblioteca/nuvem: registrar a mensagem sanitizada para diferenciar incompatibilidade, pré-condição ou recusa do backend.

## Compatibilidade
Atualização direta a partir da 1.12.24. Mantém `leapmotor-api==0.3.2`.
