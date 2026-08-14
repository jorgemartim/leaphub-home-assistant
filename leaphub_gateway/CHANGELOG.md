## 1.12.89

Corrige a última retenção longa da trava de conta observada em campo na 1.12.88.

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- status continua one-shot cooperativo como na 1.12.88;
- lista de veículos da telemetria agora usa `_get_vehicle_list` diretamente, sem o retry invisível do wrapper público;
- mensagens SLOW agora usam `_get_message_list` diretamente pelo mesmo motivo;
- em expiração de sessão, cada leitura automática permite no máximo um refresh e uma releitura;
- se um comando manual chegar durante a primeira chamada, ele vence antes de refresh/retry;
- nenhum full login é executado dentro desses helpers de leitura;
- nenhum segundo `LeapmotorApiClient` é criado e o mesmo cliente nunca é usado concorrentemente;
- ACK-first, supersessão, C10 AUTO/OFF, `climate_off` com no máximo duas transmissões e polling permanecem inalterados;
- Site 1.12.358 não faz parte desta release.
