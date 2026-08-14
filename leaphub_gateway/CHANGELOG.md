## 1.12.93

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- retira o arme SQLite da confirmação do caminho crítico depois que a nuvem já aceitou o comando;
- usa um único worker FIFO apenas para bookkeeping local, preservando a ordem das intenções e a supersessão;
- nenhuma referência ao cliente Leapmotor, credenciais ou função de dispatch entra na fila assíncrona;
- falha do arme local nunca autoriza reenvio físico; o boost idempotente do Site continua como recuperação;
- `confirmation_arm_ms` passa a medir somente o enfileiramento no caminho crítico e a duração real do SQLite é registrada separadamente;
- payloads C10, ACK-first, confirmação por modo, bounded reads, precheck sem trava global e máximo de duas transmissões OFF permanecem;
- porta-malas e cortina continuam sem retry físico automático;
- nenhum polling, timeout, composição de imagem ou critério de confirmação física foi alterado nesta release.
