## 1.12.84

Corrige confirmações antigas que permaneciam ativas depois de um comando posterior já aceito e reduz trabalho secundário da telemetria durante uso interativo.

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- dispatch ACK-first e payloads da 1.12.83 permanecem inalterados;
- supersessão de confirmação agora ocorre para toda nova intenção aceita, inclusive quando o comando posterior já retorna `confirmed` diretamente;
- telemetria interativa/FAST pula a leitura secundária de mensagens e mantém foco no status físico do veículo;
- leitura secundária continua disponível apenas no ciclo de fundo;
- nenhuma terceira transmissão, nenhum aumento de polling e nenhuma mudança de autenticação.
