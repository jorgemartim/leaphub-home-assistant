# Recuperação GitHub — Gateway 1.12.50

1. Envie somente os arquivos de `CHANGED-FILES-1.12.50.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.50`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.48` até a imagem nova estar pública.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release altera dois arquivos fora de `leaphub_gateway/`: `.github/scripts/validate_repository.py`, onde a regra de WAL passa a exigir o fallback em vez de proibir a string, e os contratos em `tests/`, que fixam a versão-alvo no próprio código e precisam do bump a cada release.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada pelo Home Assistant. Corrija a causa e execute novamente; dados em `/data`, credenciais, filas e vínculos não precisam ser removidos.
