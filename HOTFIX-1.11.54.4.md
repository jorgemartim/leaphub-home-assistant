# Hotfix 1.11.54.4

Esta versão corrige dois problemas independentes:

1. O App local falhava em `apk: not found` durante a compilação.
2. O App instalado pelo repositório falhava porque a imagem no GHCR não tinha sido criada: o workflow anterior encerrava na etapa de inicialização.

## Publicação

1. Envie todo o conteúdo deste pacote para a raiz do repositório GitHub.
2. Confirme que os workflows **Validate repository** e **Build and publish Leap Hub Gateway** ficaram verdes.
3. Em **Packages**, abra `leaphub-gateway` e altere a visibilidade para **Public**.
4. No Home Assistant, recarregue a Loja de Apps e instale a versão `1.11.54.4` do repositório GitHub.

Não use o App local `local_leaphub_gateway` depois que a versão do GitHub estiver instalada e testada.
