# Instalação de recuperação 1.12.18.2

Use somente quando a tag GHCR da 1.12.18 não puder ser publicada.

1. Publique este repositório com a versão 1.12.18.2.
2. Recarregue a Loja de Apps do Home Assistant.
3. Instale ou atualize o Gateway.

Este pacote não contém `image:`. O Home Assistant fará build local. O build foi reduzido: cloudflared não é mais baixado durante a compilação quando o túnel integrado está desativado.
