## 1.12.48

- Coleta administrativa passa a compartilhar um único critério de atualidade com o Leap Hub.
- Reinícios planejados iniciam origens locais antes do Cloudflare Tunnel e encerram o túnel antes das origens.
- Evita erros transitórios de `connection refused` durante atualização/reinício do App.
- Preserva isolamento por usuário, filas OCPP, SQLite e compatibilidade com 1.12.47.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
