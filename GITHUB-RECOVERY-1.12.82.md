# GitHub recovery — Gateway 1.12.82

Base obrigatória: commit publicado da Gateway 1.12.81 `e3d0c0997a9f40dd862b02ee3fc48957623ee4df`.

O commit funcional 1.12.82 deve manter `leaphub_gateway/config.yaml` em 1.12.81. O workflow constrói/testa/publica `ghcr.io/jorgemartim/leaphub-gateway:1.12.82`; somente depois promove o metadata e cria `[gateway-published]`.

Não usar force push. Não incluir segredos. Em caso de falha, corrigir em novo commit funcional sem promover `config.yaml` manualmente.
