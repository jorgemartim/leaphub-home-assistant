# Recuperação GitHub — Gateway 1.12.53

1. Envie somente os arquivos de `CHANGED-FILES-1.12.53.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.53`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.52` até a imagem nova estar pública.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`. A mudança é uma linha em `telemetry_engine.py`:
`token_refresh` entra na cadeia de aliases de renovação de sessão.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada pelo Home
Assistant. Corrija a causa e execute novamente.
