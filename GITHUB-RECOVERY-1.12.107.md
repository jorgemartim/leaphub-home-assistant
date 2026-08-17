# GitHub Recovery — Gateway 1.12.107

Base publicada esperada:
`db7e46301b232e076073f8c29c09f96b85b87ca3` (Gateway 1.12.106 publicado).

Escopo: corrigir exclusivamente o payload do comando remoto
`windshield_defrost`, usando `wshld=2` e preservando a receita térmica já
verificada.

Não alterar retry/resend, quick_heat, AUTO/OFF, janelas, cortina, capô, OCPP ou
promover manualmente `config.yaml`.

O instalador envia uma BRANCH, nunca force-push e nunca publica a release por si
só. Se qualquer teste falhar, preservar o worktree e não abrir/mesclar PR.
