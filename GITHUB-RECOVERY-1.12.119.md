# GitHub Recovery — Gateway 1.12.119

Base publicada obrigatória: `416acca` (Gateway 1.12.118 publicado).

Escopo: substituir somente os quatro `cmd_content` de aquecimento de volante e
retrovisores pelos payloads verificados do aplicativo internacional. Manter os
mesmos cmd IDs, direitos, PIN, autenticação, fila e confirmação por telemetria.

Não adicionar retry físico. Não alterar clima, desembaçador dianteiro, janelas,
cortina, Trips, OCPP, SQLite, dados persistidos ou cadências. Não executar
migration, limpeza, exclusão ou recálculo.

`config.yaml` permanece `1.12.118` no candidato. A promoção para `1.12.119`
depende do workflow verde, smoke test e confirmação pública do GHCR.
