# Leap Hub Gateway 1.11.77

## Comandos remotos e confirmação rápida

- Acorda o veículo antes do comando quando a API instalada disponibiliza uma operação de despertar.
- Permite que travar, destravar, climatizar e outros comandos sejam enviados mesmo com uma leitura antiga ou com o carro em repouso.
- Confirma o novo estado por até 90 segundos, consultando a cada 3 segundos.
- Mantém proteção contra repetição de comandos quando a resposta da nuvem é ambígua.
- Preserva cooldown, fila persistente, deduplicação e trava por conta.

## Ordem de atualização

1. Atualize o App **Leap Hub Gateway** no Home Assistant para 1.11.77.
2. Atualize o Leap Hub Beta para 1.12.71.
3. Execute um comando remoto e acompanhe o horário da última telemetria no painel.
