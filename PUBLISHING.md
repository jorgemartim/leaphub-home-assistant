# Publicação de novas versões

## Fluxo normal

1. Atualize o código dentro de `leaphub_gateway/`.
2. Atualize `version` em `leaphub_gateway/config.yaml`.
3. Registre as mudanças em `leaphub_gateway/CHANGELOG.md`.
4. Envie as alterações para o branch `main`.
5. O GitHub Actions valida o pacote, compila a imagem `amd64` e publica no GitHub Container Registry.
6. O Home Assistant detecta a nova versão pelo `config.yaml`.

## Nome da imagem

```text
ghcr.io/jorgemartim/leaphub-gateway:<versão>
```

Também é publicada a tag:

```text
ghcr.io/jorgemartim/leaphub-gateway:latest
```

O Home Assistant usa sempre a tag indicada por `version`, não a tag `latest`.

## Primeira publicação

Depois do primeiro build bem-sucedido:

1. Abra o perfil do GitHub.
2. Entre em **Packages → leaphub-gateway**.
3. Abra **Package settings**.
4. Confirme que a visibilidade é **Public**.

Uma imagem pública pode ser baixada pelo Home Assistant sem login no GitHub.

## Regras de versão

- Não reutilize uma versão que já foi publicada.
- Não altere o código mantendo o mesmo número de versão.
- Use versões crescentes, por exemplo `1.11.54.4`, `1.11.55` e `1.11.55.1`.
- O valor de `version` precisa corresponder à tag da imagem.

## Execução manual

Em **Actions → Build and publish Leap Hub Gateway → Run workflow**, é possível refazer a compilação da versão atual. Evite isso depois de usuários instalarem a tag; prefira publicar uma nova versão.
