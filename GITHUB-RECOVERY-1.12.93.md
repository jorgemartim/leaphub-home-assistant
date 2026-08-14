# GitHub Recovery — Gateway 1.12.93

Base publicada obrigatória:
`ce84114635f607bef170897ab8c48843c42c8b55`

Commit funcional esperado:
`fix(gateway): defer confirmation arm after accepted dispatch`

Regras:
- sem reset --hard;
- sem force push;
- sem `git add .`;
- `config.yaml` fica 1.12.92 no commit funcional;
- Site não é alterado;
- somente GitHub Actions promove 1.12.93 após validate/build/smoke/GHCR.
