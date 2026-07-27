# Recuperação GitHub — Gateway 1.12.31

Este pacote é para o repositório `jorgemartim/leaphub-home-assistant` quando ele ainda está em uma base antiga (por exemplo 1.11.54.5).

Motivo: o pacote incremental da 1.12.31 pressupunha que 1.12.30 já estivesse no GitHub. Em uma base antiga faltam módulos introduzidos entre as versões, então apenas os arquivos alterados da 1.12.31 não são suficientes.

Após enviar o conteúdo deste pacote para a raiz do repositório:

1. confira `leaphub_gateway/config.yaml` = `1.12.31`;
2. aguarde o workflow **Build and publish Leap Hub Gateway**;
3. na primeira publicação, se o workflow avisar que o GHCR está privado, altere a visibilidade do pacote `leaphub-gateway` para **Public**;
4. atualize/recarregue o repositório de Apps no Home Assistant;
5. instale/atualize o Leap Hub Gateway.

O Home Assistant passa a baixar `ghcr.io/jorgemartim/leaphub-gateway:1.12.31` pré-compilado.
