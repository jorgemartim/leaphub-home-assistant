# Hotfix 1.11.54.5

Esta versão corrige o Connector Leapmotor do App unificado.

## Correções

- instala o módulo do Connector como `leaphub_connector` no ambiente Python da imagem;
- mantém uma cópia em `/app/connector.py` para diagnóstico;
- define `PYTHONPATH=/app`;
- adiciona teste de importação durante a compilação da imagem;
- impede a publicação de uma imagem sem o módulo do Connector;
- registra no início o caminho real do módulo carregado;
- mantém OCPP, Ingress e Cloudflare sem alteração funcional.

## Atualização

1. Substitua o conteúdo do repositório GitHub pelos arquivos desta versão.
2. Aguarde os workflows **Validate repository** e **Build and publish Leap Hub Gateway** ficarem verdes.
3. Confirme que o pacote `leaphub-gateway` está público.
4. Recarregue a Loja de Apps do Home Assistant.
5. Atualize para `1.11.54.5`.

As chaves HMAC e o token do Tunnel permanecem armazenados no Home Assistant e não fazem parte do repositório.
