# GITHUB RECOVERY — Gateway 1.12.98

- Base obrigatória: `ec7bf71c72e67154f4dd04fe52ecad766c7027b7` (1.12.97 publicada).
- `config.yaml` permanece 1.12.97 no commit funcional; a promoção automática atualiza para 1.12.98 somente após imagem pública.
- Nunca usar `reset --hard`, rebase ou force push.
- Em falha antes do commit, restaurar somente os arquivos de `CHANGED-FILES-1.12.98.txt`.
- A transmissão física de `sunshade_position` é congelada; a mudança é somente confirmação pela telemetria.
- `sunshade_open/close`, clima, trunk, janelas, imagem e OCPP permanecem congelados.
- Official expõe apenas allowlist comprovado, sem unidade inferida e sem corpo bruto.
- Snapshots 1.12.80/1.12.83 continuam históricos e não são executados contra o alvo atual.
- Após push, aguardar `chore(gateway): publish 1.12.98 [gateway-published]` antes de instalar.
