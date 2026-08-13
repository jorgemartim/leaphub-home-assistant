# GitHub Recovery — Gateway 1.12.84

Base publicada obrigatória: `31a6be5ccbddb9d5c787466536751ba4505d1815`.

1. preservar `leaphub_gateway/config.yaml` anunciando 1.12.83 no commit funcional;
2. aplicar somente os arquivos listados em `CHANGED-FILES-1.12.84.txt`;
3. executar contrato 1.12.84 + matriz de comandos + `py_compile`;
4. publicar sem force push;
5. aguardar Actions construir a imagem e criar o commit automático `[gateway-published]` antes de atualizar o Home Assistant.
