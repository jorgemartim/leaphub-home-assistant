# GitHub Recovery — Gateway 1.12.92

Base publicada obrigatória:
`d5cbe8d154f8502ff9a157b0dfc9393e4009641a`

Commit funcional esperado:
`fix(gateway): release ack before redundant auth bookkeeping`

Regras:
- sem reset --hard;
- sem force push;
- sem `git add .`;
- `config.yaml` fica 1.12.91 no commit funcional;
- Site não é alterado;
- somente GitHub Actions promove 1.12.92 após validate/build/smoke/GHCR.
