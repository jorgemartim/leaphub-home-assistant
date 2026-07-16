# Gateway 1.11.71

## Isolamento por conta

- Substitui a trava global de sessão por travas independentes por assinatura/conta.
- Uma conta lenta não bloqueia a coleta de outras contas.
- O limite global `connector_max_parallel` continua sendo respeitado.
- A mesma conta continua protegida contra coleta automática, sincronização manual, remoção ou renovação concorrentes.
- Sessão reutilizável, cooldown, autenticação bloqueada e espera progressiva permanecem persistentes.
