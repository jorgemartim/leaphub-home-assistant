# Upload 1.12.49

Envie somente os arquivos listados em `CHANGED-FILES-1.12.49.txt` para a `main`.

O `config.yaml` permanece anunciando 1.12.48; `leaphub_gateway/RELEASE_TARGET` aponta para 1.12.49. O workflow promove a versão somente depois de build, testes, smoke test e acesso público à imagem GHCR.
