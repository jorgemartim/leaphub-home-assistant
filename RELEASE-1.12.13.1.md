# Leap Hub Gateway 1.12.13.1

Hotfix de recuperação da instalação da versão 1.12.13.

## Problema corrigido

O `config.yaml` apontava para `ghcr.io/jorgemartim/leaphub-gateway`, fazendo o Supervisor procurar a tag `1.12.13`. Como essa tag não estava publicada, a instalação falhava com `404 manifest unknown`.

## Solução

- removido o campo `image` desta versão de recuperação;
- o Supervisor constrói a imagem localmente usando o Dockerfile do repositório;
- nenhum endpoint, comando, banco, opção ou porta foi alterado;
- o workflow do GitHub continua publicando imagens e agora confirma se a tag ficou disponível.
