# GitHub Recovery - Gateway 1.12.117

Base publicada obrigatoria: `70e045d77682db800ef19b72c2b8111bcada989b`.

Escopo estrito: somente sunshade_close passa de close_sunshade para
control_sunshade com valor explicito 0, reutilizando a conversao existente.

Nao adicionar retry fisico. Nao recolocar cortina/janelas em ACK_FIRST.
Nao alterar janelas, clima, trunk, proximidade, Trips, OCPP, SQLite ou cadencias.

config.yaml permanece 1.12.116 no commit staged. A promocao para 1.12.117 fica
a cargo do workflow somente depois de build, smoke test e GHCR publico.
