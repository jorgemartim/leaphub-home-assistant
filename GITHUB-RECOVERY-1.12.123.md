# Recuperação GitHub — Gateway 1.12.123

Release candidata com OFF seguro do desembaçador. O pacote altera somente o
payload de desligamento do cmd 170 e metadados de versão. Não há migration,
mudança de schema, limpeza ou transformação de dados.

Validação obrigatória antes da publicação: suíte completa do Gateway, build da
imagem, validação do manifesto e acesso anônimo ao digest publicado no GHCR.
