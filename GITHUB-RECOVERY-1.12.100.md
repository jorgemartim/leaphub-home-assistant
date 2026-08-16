# GitHub Recovery — Gateway 1.12.100 REV3

A REV3 não reutiliza a working tree parcial das tentativas anteriores. Cria um `git worktree`
novo diretamente do commit publicado `121e73229072c28ca0238d9738a8505c62544753`.

Escopo: janelas C10/B10 0-100 UI -> 0-10 nativo; abrir=10; fechar=0; confirmação FAST de posição;
abrir/fechar exige quatro janelas; veredito final FAST ao site; sem retry novo; cortina/OCPP preservados.

O push é normal e `origin/main` é rechecado imediatamente antes dele. Nunca há force push.

## REV4

A REV3 passou 31 testes direcionados e parou na suíte ampla local por dois itens:
1. `Dockerfile` ainda fixava a asserção do Official Probe em 1.12.99 — corrigido.
2. `test_ocpp_sqlite_single_writer_1_12_45.py` — falha histórica Windows-only,
   documentada em releases anteriores e não causada por esta alteração.

A REV4 corrige somente o item 1 e preserva OCPP funcionalmente.
