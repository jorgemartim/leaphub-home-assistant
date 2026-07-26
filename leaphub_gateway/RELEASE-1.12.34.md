# Leap Hub Gateway 1.12.34 — recuperação do pipeline de distribuição

Esta versão corrige somente a publicação/instalação pré-compilada do Gateway.

## Mudanças

- workflow de build simplificado para um único `amd64`;
- nenhum `pytest` de runtime é executado antes de as dependências existirem na imagem;
- smoke test usa a tag exata já publicada no GHCR;
- acesso anônimo é verificado com retries, mas eventual atraso de propagação vira aviso e não apaga o sucesso do build;
- GitHub Actions publica um resumo com versão, imagem e digest;
- `CHANGELOG.md` contém somente `1.12.34`.

## Importante

O Home Assistant deve ser atualizado apenas depois do job **Build and publish Leap Hub Gateway** terminar. A imagem precisa existir no GHCR antes do Supervisor tentar instalar a mesma versão.
