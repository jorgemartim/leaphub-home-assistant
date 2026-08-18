# Leap Hub Gateway 1.12.112 — maintenance incremental de baixa latencia

## Evidencia de campo
Na 1.12.111 publicada, a maintenance continuou em 19-35 s. No mesmo recorte,
ACK de `/v1/vehicles/command` variou de ~2 ms para ~2 s, houve timeout de entrega
e timeout da API interna OCPP. Fora da maintenance, `windows_close/open` voltou a
~0,62 s de dispatch e confirmou em 0-6 s.

## Causa
`LIMIT 200` da 1.12.111 limitava somente as linhas retornadas. As consultas ainda
filtravam/ordenavam a fila por `created_at`, usavam `COALESCE` e executavam
`COUNT(*)` a cada passada. Em fila grande/disco lento, SQLite podia examinar muito
mais que 200 linhas sem esperar lock; `busy_timeout=150ms` nao limita tempo de query.

## Correcao
- discovery por `rowid` em fatias de no maximo 200 linhas;
- cursor incremental em memoria e wrap seguro;
- sem ORDER BY created_at e sem COALESCE na poda;
- COUNT de capacidade no maximo a cada 900 s, com progress handler de 40 ms;
- writer interno: espera maxima 20 ms, depois cede;
- prioridade de comando/confirmacao revalidada antes de escrever;
- nenhum indice pesado e criado durante atualizacao/startup;
- sem rede, Leapmotor ou render dentro do writer lock.

## Congelado
Matriz 40+12, SAFE retry somente climate_on/off, janelas 0-100 -> 0-10,
defrost wshld=2/0, Prepare FAST, auth/cooldown, OCPP, 5/5/8 e
8/15/25/40/60/90. `config.yaml` permanece 1.12.111 no commit funcional.
