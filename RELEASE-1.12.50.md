# Leap Hub Gateway 1.12.50 — telemetria após comando

Correção focada no fluxo observado em veículo adormecido:

- o comando continua sendo enviado uma única vez;
- ao terminar como `confirmation_pending`, o Gateway arma a janela FAST;
- a sessão autenticada é reutilizada;
- o veículo-alvo e o `request_id` ficam associados à confirmação;
- um `boost` repetido pelo site não reinicia o acompanhamento;
- estados temporários de recuperação preservam o contexto do comando.

`config.yaml` não faz parte do delta. A publicação permanece em duas fases.
