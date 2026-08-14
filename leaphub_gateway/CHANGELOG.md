## 1.12.92

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- remove somente o bookkeeping redundante de autenticação que ocorria depois de um comando já aceito pela nuvem em sessão reutilizada;
- o sucesso de autenticação continua sendo registrado quando um login real acontece;
- mede `post_dispatch_local_ms` para que qualquer novo atraso depois do dispatch fique atribuído;
- adiciona rastreamento de etapas lentas da telemetria (lock de sessão, criação de cliente, reserva de autenticação, login, bookkeeping, lista, mensagens, status e serialização);
- o rastreamento é diagnóstico: não muda timeout, polling, retry, payload ou quantidade de chamadas;
- bounded reads 1.12.89, confirmação por modo 1.12.90 e precheck sem trava global 1.12.91 permanecem;
- ACK-first, supersessão, payload C10 e máximo de duas transmissões permanecem;
- nenhuma segunda sessão Leapmotor, wake artificial ou concorrência do mesmo cliente é criada.
