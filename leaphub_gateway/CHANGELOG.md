## 1.12.110

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- corrige regressão de latência comprovada em campo: `CONFIRM_ARM_DIAG stage=boost` chegou a 17.887 ms apesar de o despacho remoto terminar em ~0,6 s;
- separa agenda/confirmacao (`schedule_lock`) da trava global usada por fila, entrega, autenticação e outros bookkeepings;
- tira retenção/manutenção do laço do scheduler e executa-a em worker local dedicado;
- remove a trava global de leituras read-only do scheduler e do caminho FAST de confirmação;
- mantém a transação `BEGIN IMMEDIATE` da fila, mas sem segurar `self.lock` enquanto SQLite aguarda;
- adiciona `CONFIRM_SCHED_DIAG` e `TELEMETRY_MAINTENANCE_DIAG` para detectar nova regressão;
- não altera payload físico, janelas 0-100 -> 0-10, matcher de janelas, defrost ON/OFF, retry, cooldown/auth, OCPP nem cadência 5/5/8;
- mantém `config.yaml` em 1.12.109 até publicação normal via CI/GHCR.
