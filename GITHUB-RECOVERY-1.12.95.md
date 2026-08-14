# GitHub Recovery — Gateway 1.12.95

Base publicada obrigatória:
`b96097d2c05d68a6079729ce194309dd3405acc4`

Commit funcional esperado:
`fix(gateway): accelerate isolated visual rendering`

Regras:
- sem reset --hard;
- sem rebase;
- sem force push;
- sem `git add .`;
- `config.yaml` fica 1.12.94 no commit funcional;
- Site não é alterado;
- somente GitHub Actions promove 1.12.95 após validate/build/smoke/GHCR.
