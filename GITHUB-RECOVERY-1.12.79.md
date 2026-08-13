# Recuperação GitHub — Gateway 1.12.79

1. Envie somente os arquivos de `CHANGED-FILES-1.12.79.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.79`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.78` até a imagem nova estar pública. O commit inicial da 1.12.79 não toca esse arquivo.
4. Aguarde validação, build, smoke test e verificação anônima do GHCR.
5. O workflow promove `config.yaml` para `1.12.79` somente depois dessas verificações.

Mudança funcional restrita à climatização C10/B10/B05:

- `climate_off` usa `ac_switch` com `operate=off`;
- `climate_on` usa AUTO com `operate=auto` e `mode=nohotcold`;
- a confirmação passa a usar o modo físico (`off`, `auto`, `cooling`, `heating`) em vez de apenas `ac_switch`;
- `rapid_cooling` / `rapid_heating` ficam somente como fallback quando não entram em conflito;
- a segunda tentativa protegida repete exatamente o mesmo estado; não há terceira transmissão e não há aumento de polling.

O site Beta já deve estar na 1.12.352 ou superior antes da validação física desta release.
