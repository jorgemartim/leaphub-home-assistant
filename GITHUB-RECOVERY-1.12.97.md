# GITHUB RECOVERY — Gateway 1.12.97

- Base funcional obrigatória: `215c4215d58ce3e2439c1bb2dcec0041995414c4` (1.12.96 publicada).
- Commit funcional 1.12.97 deve ser fast-forward normal sobre essa base.
- `config.yaml` permanece 1.12.96 no commit funcional; `RELEASE_TARGET` fica 1.12.97.
- Nunca usar `reset --hard`, rebase ou force push.
- Em falha de pré-validação, restaurar somente os arquivos listados em `CHANGED-FILES-1.12.97.txt`.
- Produção/Site não pertencem a este hotfix.
- O hotfix altera somente empacotamento/import da sonda Official; comandos, 5/5/8, telemetria, imagem e OCPP permanecem congelados.
- `command_ack_first_1_12_80_contract.py` e `fast_controls_1_12_83_contract.py` são snapshots históricos literais e não entram na suíte cumulativa de releases atuais.
- Após push, aguardar o commit automático `chore(gateway): publish 1.12.97 [gateway-published]` antes da instalação no Home Assistant.
