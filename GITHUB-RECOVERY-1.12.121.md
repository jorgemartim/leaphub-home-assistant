# GitHub Recovery — Gateway 1.12.121

Base obrigatória: `306a357` (Gateway 1.12.120 candidato).

Branch: `codex/gateway-1.12.121-seat-comfort-payloads`.

Esta release altera apenas o contrato dos comandos de banco e versões de
runtime. Não contém migration, exclusão, recálculo nem alteração de persistência.
O CI promove `config.yaml` de 1.12.120 para 1.12.121 somente depois de publicar e
validar a imagem exata.
