## 1.12.113

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- janelas e cortina deixam o ACK-first: o worker respeita o remoteCtlId antes de liberar outra ação mecânica na mesma conta;
- nenhum comando físico é repetido; timeout do result/query continua como ACK aceito + confirmação FAST pendente;
- janela FAST esgotada agora anuncia resultado terminal `unconfirmed`, sem marcar `not_applied` e sem reenvio;
- diário local encerra `sent + confirmation_pending` após 210s se o anúncio best-effort ao site se perder;
- diagnóstico `CONFIRM_STATE_DIAG` mostra apenas estados/percentuais seguros de janelas/cortina durante confirmação;
- imagem continua baseada somente em telemetria confirmada; não existe atualização visual otimista;
- preserva maintenance 1.12.112, SQLite writer, schedule_lock, auth/cooldown, OCPP, SAFE retry e cadências.
- mantém config.yaml em 1.12.112 até a publicação normal via CI/GHCR.
