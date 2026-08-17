# GitHub Recovery — Gateway 1.12.106

Base publicada esperada:
`17daddeeb08651bf3567da18f48e801fcc9a65a0` (Gateway 1.12.105 publicado).

Escopo: corrigir exclusivamente a ordem de execução do diagnóstico tipado de
clima/conforto para restaurar a conclusão da telemetria.

Sem alteração de comandos físicos, retry, janelas, cortina, OCPP ou promoção
manual de `config.yaml`.

Se qualquer teste ou CI falhar, manter 1.12.105 publicada e preservar o worktree.
Nunca usar force push.
