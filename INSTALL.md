# Instalação e atualização rápida

O Leap Hub Gateway usa imagem pré-compilada no GitHub Container Registry (GHCR).

## Publicar uma nova versão pelo GitHub

1. Envie os arquivos da nova versão para a branch `main` do repositório.
2. Abra **Actions → Build and publish Leap Hub Gateway**.
3. Aguarde o workflow terminar com sucesso, inclusive **Verify anonymous image access**.
4. Só depois atualize/recarregue o repositório na Loja do Home Assistant.
5. Instale ou atualize o Leap Hub Gateway normalmente.

O Home Assistant baixará `ghcr.io/jorgemartim/leaphub-gateway:<versão>` pronto. Ele não deve executar o build do Dockerfile durante uma atualização normal.

## Primeira publicação do GHCR

O pacote `leaphub-gateway` precisa estar **Public** no GitHub Packages para o Home Assistant baixar a imagem sem credenciais. Se o workflow falhar na verificação anônima, confira a visibilidade do pacote.

## Recuperação

O Dockerfile continua no repositório para desenvolvimento ou recuperação controlada. Não remova `image:` da versão normal apenas para contornar uma falha de publicação; primeiro corrija a imagem/tag no GHCR para evitar que instalações diferentes usem builds diferentes.


## 1.12.34 — imagem pré-compilada

O App declara `image: ghcr.io/jorgemartim/leaphub-gateway`. Após o push, aguarde o workflow **Build and publish Leap Hub Gateway** ficar verde. O último passo valida acesso anônimo à tag exata; isso evita anunciar uma atualização que o Home Assistant ainda não consegue baixar. Na primeira publicação do pacote GHCR pode ser necessário tornar o pacote público uma única vez e reexecutar o workflow.


> Importante: só atualize o App no Home Assistant depois que o workflow de build da versão 1.12.34 estiver verde.
