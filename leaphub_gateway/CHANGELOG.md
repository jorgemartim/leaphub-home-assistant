## 1.12.85

Reduz a espera do primeiro comando quando a telemetria já está consultando um veículo parado/dormindo, sem alterar o caminho rápido dos comandos.

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- leituras automáticas de lista, status e mensagens usam chamadas one-shot da `leapmotor-api==0.3.2`;
- refresh/login de sessão volta a ser coordenado pelo Gateway, onde a prioridade manual pode ceder entre etapas;
- o comando manual continua usando o cliente original, ACK-first e os payloads já homologados;
- sessão persistente, supersessão, resultado imediato Gateway→Site e lanes do Site permanecem inalterados;
- nenhuma terceira transmissão, nenhum wake artificial e nenhum aumento de polling.
