# Recuperação GitHub — Gateway 1.12.51

1. Envie somente os arquivos de `CHANGED-FILES-1.12.51.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.51`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.48` até a imagem nova estar pública.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release altera o `leaphub_gateway/Dockerfile`. O autoteste da imagem deixa de exigir um journal
fixo e passa a validar o contrato: WAL quando o volume aceita, DELETE quando não aceita, sempre com
o modo reportado pelo motor. Foi a asserção fixa que reprovou o build da 1.12.50.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada pelo Home
Assistant. Corrija a causa e execute novamente; dados em `/data`, credenciais, filas e vínculos não
precisam ser removidos.
