# Leap Hub Gateway 1.12.42

Release de distribuição segura sobre a 1.12.41.

- Mantém runtime, filas persistentes, OCPP, Connector e opções da 1.12.41.
- Corrige o smoke test do GitHub Actions para não importar `gateway_manager.py`, que é um processo de longa duração.
- Adiciona timeouts defensivos ao pull, inspect e smoke test da imagem publicada.
- Mantém publicação pré-compilada via GHCR.
- `config.yaml` permanece em 1.12.41 enquanto a imagem 1.12.42 não estiver pública; `RELEASE_TARGET` aponta para 1.12.42 e o workflow promove a versão somente após confirmar pull anônimo.
- Não altera schema de opções nem dados persistentes em `/data`.
