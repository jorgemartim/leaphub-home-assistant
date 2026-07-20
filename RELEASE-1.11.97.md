# Leap Hub Gateway 1.11.97

## Controles remotos e prioridade

- Comandos manuais continuam isolados por conta Leapmotor e passam a verificar a prioridade em intervalos menores.
- Chamadas automáticas de telemetria usam timeout menor, evitando que uma única leitura mantenha o comando atrás da conta por quase um minuto.
- A telemetria cede antes de consultas opcionais e antes de cada veículo quando há comando manual pendente.
- `quick_cool` e `quick_heat` passam a participar da verificação de estado, sem repetição automática cega.
- `climate_on` e `climate_off` continuam sendo os únicos comandos de climatização com uma repetição idempotente protegida.
- O diagnóstico de `climate_off` agora informa corretamente quando uma leitura nova ainda mostra o sistema ligado.
- O log diferencia despertar real, repetição segura, confirmação direta e confirmação pendente.
- Corrigida uma dupla redução do contador interno de operações manuais.

Nenhuma credencial, e-mail, VIN, PIN ou token é gravado nos novos diagnósticos.
