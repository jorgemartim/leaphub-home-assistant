## 1.12.117

A distribuição continua pré-compilada no GHCR oficial e mantém a publicação em duas fases.

- corrige somente o fechamento da cortina do teto;
- sunshade_close passa pelo mesmo control_sunshade usado pela posição,
  enviando explicitamente o valor nativo 0;
- sunshade_open permanece em open_sunshade;
- sunshade_position e sua conversão 0-100 -> 0-10 permanecem inalterados;
- continua existindo uma unica transmissão por intencao de cortina;
- nenhum retry fisico novo foi adicionado;
- janelas e cortina continuam fora de ACK_FIRST e preservam o fence mecanico;
- SAFE_STATE_RETRY_COMMANDS continua somente climate_on/climate_off;
- proximidade, janelas, trunk, clima, Trips, OCPP, SQLite writer e cadencias
  permanecem congelados;
- config.yaml permanece em 1.12.116 ate o CI construir, testar, fazer smoke
  test e confirmar acesso anonimo a imagem GHCR 1.12.117.
