# Leap Hub Gateway 1.12.43 — OCPP Fair Queue

## Filas OCPP

- replay justo por usuário/proprietário, preservando FIFO estrito por wallbox;
- uma wallbox ou usuário com backlog não monopoliza mais os lotes globais;
- filas antigas sem proprietário conhecido continuam isoladas pela identidade da wallbox;
- resultados de comandos OCPP usam o mesmo escalonamento justo;
- o painel do Gateway mostra backlog agregado sem expor IDs de usuário ou Charge IDs.

## Compatibilidade

- atualização sobre 1.12.42;
- sem reset do SQLite existente;
- tabela `queue_owners` é aditiva e criada com `CREATE TABLE IF NOT EXISTS`;
- filas `event_queue`, `command_result_queue`, rotas, quarentena e Charge IDs existentes são preservados;
- `config.yaml` permanece em 1.12.42 até a imagem 1.12.43 estar pública no GHCR.
