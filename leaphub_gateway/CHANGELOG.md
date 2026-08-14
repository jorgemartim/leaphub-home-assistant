## 1.12.94

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- separa telemetria essencial da composição da imagem oficial;
- persiste o estado do veículo antes de qualquer render local;
- usa um único worker visual que recebe somente snapshot JSON e ZIP local;
- imagem não recebe cliente Leapmotor, sessão, token, credenciais ou callback de comando;
- galeria pesada de diagnóstico passa a existir somente sob solicitação explícita;
- jobs visuais antigos são descartados quando uma assinatura mais nova chega;
- metadados visuais cacheados mantêm deduplicação estável sem bloquear o estado;
- controles, polling, timeouts, payloads e Site permanecem inalterados.
