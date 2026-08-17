# GitHub Recovery — Gateway 1.12.108

Base publicada esperada:
`19e88f57b69dbd8b19a0465f0c97921bbadc3c65` (Gateway 1.12.107 publicado).

Escopo: corrigir somente a coordenação entre o arme FAST e um poll antigo em
finalização, incluindo a espera soft `recovering/error` que anteceda um comando
manual aceito.

Proteções obrigatórias: não furar `cooldown`, `auth_required` ou rate-limit; não
alterar payloads físicos, retry/resend, windows, sunshade, hood ou OCPP; não
promover `config.yaml` manualmente.

O pacote cria e envia somente uma branch candidata. Merge/publicação permanecem
fora do instalador. Em caso de falha de teste ou base diferente, o processo para
antes de tocar na main.
