## 1.12.91

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- o precheck do comando manual não adquire mais a trava global `TelemetryEngine.lock` para ler a assinatura local;
- `engine_lock_wait_ms` permanece no diagnóstico com valor zero, preservando o formato dos logs;
- a leitura da assinatura usa SQLite diretamente com teto de 0,75s; em `locked/busy`, falha como temporária antes de qualquer dispatch;
- trava por conta, `_session_operation_lock`, cliente Leapmotor persistente e serialização por conta permanecem inalterados;
- confirmação mode-aware de AUTO/COOL/HEAT da 1.12.90 permanece ativa e testada;
- bounded reads, ACK-first, payload C10, máximo de duas transmissões OFF e polling permanecem inalterados;
- nenhum segundo cliente Leapmotor e nenhuma nova chamada de rede foram adicionados.
