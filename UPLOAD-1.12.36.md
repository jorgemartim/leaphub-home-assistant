# Upload da 1.12.36

1. Parta de um repositório 1.12.35 íntegro.
2. Envie somente os arquivos do pacote de arquivos alterados, preservando os caminhos.
3. Confirme `leaphub_gateway/config.yaml` com `version: "1.12.36"`.
4. Aguarde o workflow GHCR ficar verde e publicar a tag `1.12.36`.
5. Só então atualize o App no Home Assistant.

A pasta `.github` não é alterada nesta versão.
