## 1.12.88

Entrega o handoff cooperativo que a antiga 1.12.85 deveria ter feito, mantendo a 1.12.87/restauração 1.12.84 como base estável.

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- somente a leitura automática principal de status deixa de usar o retry invisível de `get_vehicle_status()` da leapmotor-api 0.3.2;
- o mesmo `LeapmotorApiClient` persistente continua sendo usado;
- nenhum segundo cliente e nenhum uso concorrente do mesmo cliente;
- cada status automático faz uma chamada one-shot por etapa;
- token expirado permite no máximo um refresh e uma releitura;
- prioridade manual é verificada antes/depois da leitura, refresh e releitura;
- lista de veículos, mensagens, caminho manual e payloads permanecem como na 1.12.87;
- ACK-first, supersessão e anúncio imediato Gateway→Site permanecem;
- `climate_off` continua limitado a no máximo duas transmissões idênticas;
- nenhuma terceira transmissão, wake artificial ou aumento de polling;
- Site permanece em 1.12.358 e não faz parte desta release.
