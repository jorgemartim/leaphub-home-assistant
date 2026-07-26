# Recuperação de publicação 1.12.38

Esta versão mantém a imagem pré-compilada `ghcr.io/jorgemartim/leaphub-gateway` e o fluxo atual do repositório.

Se a publicação automática falhar, preserve o commit da 1.12.38, execute novamente o workflow de build e confirme que a tag exata publicada passa no smoke test anônimo antes de atualizar o repositório do Home Assistant.

Não publique uma imagem antiga com a tag 1.12.38 e não copie credenciais do ambiente para artefatos de build.
