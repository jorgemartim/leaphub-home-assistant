# Leap Hub Gateway 1.12.45

## Correções baseadas nos logs reais da 1.12.44

- Serializa escritores do SQLite OCPP para evitar `database is locked` durante reconexões intensas.
- Mantém WAL e leituras concorrentes; somente gravações são coordenadas.
- `prune_queues` sai do caminho crítico de cada evento e roda no máximo uma vez por janela.
- Coalescing de gravações idênticas de rota/owner durante reconnect storm.
- Diagnóstico agregado de reconnect storm, retries/falhas de lock e saúde do SQLite sem expor IDs.
- `/v1/vehicles/sync` passa a aceitar execução em worker com `/v1/vehicles/sync/status`, evitando manter o Cloudflare HTTP aberto por ~60s.
- Health check informa latência, falhas consecutivas e último OK/erro.
- Nenhuma fila existente é apagada. Nenhuma alteração destrutiva do SQLite.
