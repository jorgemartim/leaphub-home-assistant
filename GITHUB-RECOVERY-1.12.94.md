# GitHub Recovery — Gateway 1.12.94

Base publicada obrigatória:
`47d0d0331ed277750e1ea45128a6ca5d436727dd`

Commit funcional esperado:
`fix(gateway): isolate telemetry from local visual rendering`

Regras:
- sem reset --hard;
- sem force push;
- sem `git add .`;
- `config.yaml` fica 1.12.93 no commit funcional;
- Site não é alterado;
- somente GitHub Actions promove 1.12.94 após validate/build/smoke/GHCR.
