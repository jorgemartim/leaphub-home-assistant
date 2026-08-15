# GITHUB RECOVERY — Gateway 1.12.96

- Base funcional obrigatória: `672d4dcca0f6928d21f8eb6141bf815fb9bdb5e8` (1.12.95 publicada).
- Commit funcional 1.12.96 deve ser fast-forward normal sobre essa base.
- `config.yaml` permanece 1.12.95 no commit funcional; `RELEASE_TARGET` vira 1.12.96.
- Nunca usar `reset --hard`, rebase ou force push.
- Em falha de pré-validação, restaurar somente os arquivos listados em `CHANGED-FILES-1.12.96.txt`.
- Produção/Site não pertencem a este pacote.
- Após push, aguardar o commit automático `chore(gateway): publish 1.12.96 [gateway-published]` antes da instalação no Home Assistant.
