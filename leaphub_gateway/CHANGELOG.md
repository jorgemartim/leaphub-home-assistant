## 1.12.112

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- corrige a regressao de latencia medida na 1.12.111: maintenance ainda consumia 19-35 s apesar do lote de 200;
- troca discovery por fatia incremental de no maximo 200 rowids, sem ORDER BY created_at/COALESCE global;
- COUNT de capacidade deixa de rodar a cada minuto: no maximo a cada 15 min e com progress handler de ~40 ms;
- maintenance espera no maximo ~20 ms pelo writer interno e cede a comando/confirmacao antes e depois da discovery;
- preserva schedule_lock e sqlite_writer_lock, SELECT concorrente em WAL e _queue_event atomico;
- preserva exatamente a rota de ACK do comando e todos os handlers fisicos, mudando neles somente a versao;
- nao altera payload, SAFE retry, auth/cooldown, OCPP, janelas, defrost, Prepare nem cadencia 5/5/8;
- mantem config.yaml em 1.12.111 ate a publicacao normal via CI/GHCR.
