# Publicação do Leap Hub Gateway

## Fluxo normal — imagem pré-compilada

1. Atualize o código e `version` em `leaphub_gateway/config.yaml`.
2. Mantenha obrigatoriamente:

```yaml
image: "ghcr.io/jorgemartim/leaphub-gateway"
```

3. Envie para `main`.
4. O GitHub Actions valida o repositório e constrói a imagem `amd64`.
5. O build usa cache de camadas. Como `requirements.txt` é copiado antes do código, mudanças normais de Python não recompilam/rebaixam as dependências.
6. A imagem exata é testada antes da publicação.
7. São publicadas as tags `<version>` e `latest`.
8. O workflow encerra a autenticação do GHCR e confirma que a tag versionada pode ser consultada anonimamente.
9. Somente após o workflow verde, recarregue a Loja de Apps do Home Assistant.

O Home Assistant usa automaticamente a tag igual ao campo `version` do `config.yaml`.

## Release notes

`leaphub_gateway/CHANGELOG.md` deve conter **somente a versão atual**. O histórico permanece no Git/GitHub e não é repetido na tela de atualização do Home Assistant.

## Visibilidade

O pacote GHCR precisa ser público. O Home Assistant não deve depender de token pessoal ou credenciais do GitHub para instalar o Gateway.
