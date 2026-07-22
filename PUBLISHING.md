# Publicação de novas versões

## Fluxo rápido normal

1. Atualize `leaphub_gateway/` e o número de `version` em `config.yaml`.
2. Envie o repositório para a branch `main`.
3. Abra **Actions → Build and publish Leap Hub Gateway**.
4. Aguarde a etapa **Verify published manifest** ficar verde.
5. Abra **Packages → leaphub-gateway** e confirme que a versão está pública.
6. Somente depois recarregue o repositório no Home Assistant.

O Home Assistant solicitará exatamente:

```text
ghcr.io/jorgemartim/leaphub-gateway:<version>
```

A atualização só deve aparecer na Loja depois que essa tag existir. Isso impede o erro `manifest unknown`.

## Visibilidade do GHCR

Na primeira publicação ou depois de recriar o pacote:

1. Abra **Packages → leaphub-gateway** no GitHub.
2. Entre em **Package settings**.
3. Defina a visibilidade como **Public**.

O Home Assistant não possui credenciais do seu GitHub e precisa baixar a imagem publicamente.

## Cache e validação

O workflow usa cache Buildx. Depois da primeira compilação, versões que alteram apenas o código reaproveitam as camadas de dependências. Antes da publicação definitiva, o workflow:

- valida o repositório;
- compila a imagem `amd64`;
- executa o autoteste dentro da imagem exata;
- publica as tags de versão e `latest`;
- confirma que o manifesto `linux/amd64` está disponível no GHCR.

## Recuperação

Se a publicação GHCR falhar, use o pacote separado `1.12.18.1-recuperacao`, que não possui `image:` e permite build local. Não altere o pacote rápido removendo o campo manualmente.
