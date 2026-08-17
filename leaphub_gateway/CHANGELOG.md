## 1.12.108

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- fecha a corrida entre um poll antigo em finalização e uma nova confirmação FAST armada após um comando;
- preserva `next_run_at` e `command_poll_count` da janela nova quando eles nasceram depois do snapshot do poll;
- um comando aceito pode cortar apenas espera `recovering/error` anterior; `cooldown` e `auth_required` continuam bloqueios duros;
- preserva cooldown/autenticação que sejam gravados enquanto um poll antigo termina trabalho local;
- mantém a cadência pós-despacho 5/5/8 e o backoff seguro 8/15/25/40/60/90;
- não altera payload, retry/resend físico, janelas, cortina, capô, OCPP, HMAC ou contrato do Site.
