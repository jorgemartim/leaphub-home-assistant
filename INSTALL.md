# Instalação rápida do Leap Hub Gateway 1.12.18

1. Publique este repositório na branch `main`.
2. Aguarde o workflow **Build and publish Leap Hub Gateway** concluir, inclusive **Verify published manifest**.
3. Confirme que `ghcr.io/jorgemartim/leaphub-gateway:1.12.18` está público.
4. Recarregue o repositório na Loja de Apps do Home Assistant.
5. Atualize para 1.12.18.

O Home Assistant apenas baixa a imagem pronta. Não recarregue a Loja antes da publicação da tag, ou o Supervisor encontrará a versão sem encontrar a imagem.

As configurações em `/data` permanecem preservadas durante a atualização.
