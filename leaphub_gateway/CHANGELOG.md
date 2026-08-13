## 1.12.82

Prioridade manual real: telemetria não pode mais manter a conta ocupada por dezenas de segundos quando o proprietário envia um comando.

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- leituras automáticas de rede recebem teto curto de 4s somente enquanto possuem a trava da conta; o timeout normal do cliente é restaurado imediatamente depois;
- login criado especificamente pela telemetria também usa o teto curto, enquanto login/dispatch de comando continuam no orçamento normal;
- se um comando manual aparecer durante uma leitura automática, o ciclo de telemetria cede a conta sem transformar essa preempção em falha de sessão;
- a consulta somente-leitura de `account_auth_status` deixa de disputar o lock global do motor; reservas e mutações de autenticação continuam transacionais e protegidas;
- ACK-first, clima AUTO e OFF C10, retry exato de no máximo duas transmissões e anúncio imediato ao site permanecem intactos;
- nenhuma terceira transmissão e nenhum aumento de polling.
