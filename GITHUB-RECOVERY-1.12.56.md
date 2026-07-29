# Recuperação GitHub — Gateway 1.12.56

1. Envie somente os arquivos de `CHANGED-FILES-1.12.56.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.56`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.53` até a imagem nova estar pública.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`. São duas mudanças em `telemetry_engine.py` e `connector_server.py`:
a quebra de `engine_precheck_ms` em três contadores e um teto de 20s na aquisição da trava global do motor
no caminho do comando. Estourar o teto vira 503 transitório, com o comando preservado na fila e nenhuma
ação física enviada ao veículo.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada pelo Home
Assistant. Corrija a causa e execute novamente.
