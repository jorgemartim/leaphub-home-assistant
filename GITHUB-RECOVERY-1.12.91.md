# GitHub Recovery — Gateway 1.12.91

Base publicada esperada: `8c1d09285d65aee1c4c76d5b11324768d5f4b7b4` (`chore(gateway): publish 1.12.90 [gateway-published]`).

Commit funcional esperado: `fix(gateway): remove global lock from command precheck`

Publicação em duas fases: commit funcional com `RELEASE_TARGET=1.12.91` e `config.yaml=1.12.90`; depois GitHub Actions publica a imagem e promove `config.yaml`.

Não usar force push, reset hard ou `git add .`. Não tocar no Site.
