# GitHub Recovery - Gateway 1.12.118

Base publicada obrigatória: `fa5c5c9`.

Escopo: atualizar somente as dependências criptográficas/visuais, fechar
conexões SQLite OCPP ao sair de contexto e isolar os testes que vazavam estado.

Não alterar comandos físicos, Trips, telemetria, proximidade, cadências ou dados
persistidos. Não executar migration, limpeza de fila ou recálculo.

`config.yaml` permanece `1.12.117` no candidato. A promoção para `1.12.118`
depende do workflow verde, smoke test e confirmação pública do GHCR.
