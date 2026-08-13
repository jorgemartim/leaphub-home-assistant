# Recuperação GitHub — Gateway 1.12.80

Base obrigatória: 1.12.79 publicada.

1. Envie somente os arquivos de `CHANGED-FILES-1.12.80.txt`.
2. `RELEASE_TARGET` deve ficar 1.12.80.
3. Preserve `leaphub_gateway/config.yaml` em 1.12.79 no commit funcional.
4. O workflow só promove `config.yaml` depois de build, testes, GHCR e smoke test.
5. Não alterar Produção/site nesta etapa.
