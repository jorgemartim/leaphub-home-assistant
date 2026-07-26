# Leap Hub Gateway 1.12.33

Correção de distribuição da 1.12.32.

## Correções

- O workflow não executa mais testes de runtime antes de instalar as dependências da imagem.
- A validação pré-build agora é estática/sintática.
- A própria imagem publicada continua sendo testada depois do build.
- A tag exata do GHCR continua sendo verificada antes de considerar o release pronto.

## Impacto

Não altera banco, OCPP, Wallbox, filas, comandos remotos ou configurações salvas do Home Assistant.
