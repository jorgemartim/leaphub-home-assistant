# GitHub recovery — Gateway 1.12.37

Base esperada: 1.12.36 já publicada e funcional.

Esta versão preserva o pipeline GHCR e altera somente o runtime/testes necessários para recuperar uma sessão expirada quando a verificação remota pré-envio recusa o token. Suba os arquivos alterados na raiz do repositório, aguarde o workflow de build publicar `ghcr.io/jorgemartim/leaphub-gateway:1.12.37` e somente depois atualize o App no Home Assistant.
