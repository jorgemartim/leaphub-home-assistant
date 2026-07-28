# Recuperação GitHub — Gateway 1.12.49

1. Envie somente os arquivos de `CHANGED-FILES-1.12.49.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.49`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.48` até a imagem nova estar pública.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada pelo Home Assistant. Corrija a causa e execute novamente; dados em `/data`, credenciais, filas e vínculos não precisam ser removidos.
