# GitHub Recovery — Gateway 1.12.83

Base obrigatória: commit publicado da Gateway 1.12.82.

Fluxo:
1. sincronizar com `origin/main`;
2. confirmar `leaphub_gateway/config.yaml` em 1.12.82;
3. aplicar somente os arquivos listados em `CHANGED-FILES-1.12.83.txt`;
4. executar contrato 1.12.83 + matriz de comandos + py_compile;
5. manter `config.yaml` fora do commit funcional;
6. push sem force;
7. aguardar Validate/Build/Smoke/GHCR e commit automático `[gateway-published]`.

Rollback antes do push: restaurar os arquivos alterados a partir do HEAD 1.12.82.
Após publicação: instalar novamente a imagem pública 1.12.82 se a homologação física detectar regressão.

Nunca incluir segredos, tokens, cookies ou material de assinatura.
