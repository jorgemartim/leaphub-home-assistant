# Publicação do Leap Hub Gateway

A versão anunciada ao Home Assistant só pode mudar depois que a imagem pré-compilada correspondente estiver disponível anonimamente no GHCR.

## Fluxo seguro

1. O código do próximo Gateway usa a versão indicada em `leaphub_gateway/RELEASE_TARGET`.
2. `leaphub_gateway/config.yaml` continua anunciando a última versão comprovadamente instalável.
3. O GitHub Actions valida toda a suíte e compila a imagem `ghcr.io/jorgemartim/leaphub-gateway:<RELEASE_TARGET>`.
4. O workflow executa smoke test da imagem exata.
5. O login Docker é removido e o manifest é consultado anonimamente.
6. Se o acesso anônimo falhar, o workflow falha e `config.yaml` não muda. O Home Assistant continua oferecendo a versão anterior.
7. Somente após o acesso anônimo ser confirmado o workflow promove `config.yaml`, regenera os checksums e faz um commit automático com `[gateway-published]`.

## Primeira publicação no GHCR

Se a imagem for criada mas a etapa de acesso anônimo falhar, abra a configuração do pacote `leaphub-gateway` no GitHub Packages e torne o pacote público. Depois execute novamente o workflow `Build and publish Leap Hub Gateway`.

## Segurança

Nunca envie ao GitHub `storage`, SQLite de runtime, senhas, tokens, chaves HMAC ou credenciais Leapmotor/OCPP.
