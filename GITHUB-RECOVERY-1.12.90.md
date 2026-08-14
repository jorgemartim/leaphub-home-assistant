# GitHub Recovery — Gateway 1.12.90

Base publicada esperada: `33c89232c1a3582f41367580723377a05c5f53ac`
(`chore(gateway): publish 1.12.89 [gateway-published]`).

Commit funcional esperado:
`fix(gateway): confirm climate by physical mode`

A publicação deve continuar em duas fases:
1. commit funcional com `RELEASE_TARGET=1.12.90` e `config.yaml=1.12.89`;
2. GitHub Actions valida/builda/publica e cria `[gateway-published]`, promovendo `config.yaml`.

Não usar force push, reset hard ou `git add .`.
Não tocar no Site.
