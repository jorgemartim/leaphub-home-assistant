# Recuperação do GitHub — Gateway 1.12.35

Use este pacote somente quando o repositório GitHub estiver incompleto. Em uma base 1.12.34 íntegra, prefira os arquivos alterados.

A 1.12.35 preserva exatamente o pipeline pré-compilado estabilizado na 1.12.34 e altera apenas o runtime do Gateway, testes, versão e documentação de release.

Após o upload, confirme `leaphub_gateway/config.yaml` com `version: "1.12.35"`, aguarde o workflow de build publicar a tag GHCR e só então atualize o App no Home Assistant.
