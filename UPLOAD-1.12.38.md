# Publicação 1.12.38

1. Aplique somente os arquivos de `leaphub-gateway-1.12.38-arquivos-alterados.zip` sobre o repositório da 1.12.37.
2. Confirme que não existem arquivos `__pycache__`, segredos, tokens ou dados de execução no commit.
3. Execute os contratos e a compilação Python.
4. Publique a imagem exata `ghcr.io/jorgemartim/leaphub-gateway` pelo workflow atual.
5. Confirme o smoke test e o acesso anônimo à imagem antes de atualizar o App no Home Assistant.
6. Reinicie o App e verifique `/health`, o mapa de conexões e um comando manual controlado.

O pacote de arquivos alterados não contém APKs, credenciais, dados do veículo ou código decompilado.
