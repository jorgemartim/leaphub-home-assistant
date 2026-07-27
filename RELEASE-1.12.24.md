# Leap Hub Gateway 1.12.24 — Strict OCPP FIFO

## Objetivo
Endurecer a entrega de eventos OCPP sem alterar credenciais, portas, comandos, telemetria Leapmotor ou configuração existente do add-on.

## Alterações
- Replay da `event_queue` passa a ser FIFO estrito por `target_name + Charge ID`.
- Um evento mais novo não ultrapassa outro da mesma wallbox quando o anterior está em backoff ou falhou novamente.
- Outras wallboxes continuam sendo processadas normalmente.
- Promoção de rota entre ambientes mantém a ordem de IDs da fila.
- Nenhuma migração de configuração e nenhuma mudança de porta.

## Compatibilidade
Atualização direta a partir da 1.12.23. Recomendado atualizar o Gateway antes da Beta Leap Hub 1.12.208.
