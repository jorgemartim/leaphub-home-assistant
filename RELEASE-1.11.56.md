# Leap Hub Gateway 1.11.56

## Sincronização automática adaptativa

- 5 segundos durante viagem e carregamento.
- 10 segundos quando o cabo está conectado e a recarga ainda não começou.
- 30 segundos estacionado e 120 segundos em repouso prolongado.
- Recuo exponencial, jitter e pausa automática de 30 minutos ao detectar limitação da nuvem.
- O Gateway não promete imunidade a bloqueios de uma API não oficial; o perfil reduz chamadas quando o veículo está inativo e reage a sinais de limitação.

## ABRP

O site envia a leitura mais recente no primeiro evento recebido de cada janela alinhada de cinco minutos.
