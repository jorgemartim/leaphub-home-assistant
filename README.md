# Gateway 1.12.79 — pacote de revisão

Este pacote **não publica nem instala automaticamente** o Gateway. Ele existe porque a integração de escrita do GitHub foi bloqueada nesta rodada antes de qualquer modificação remota.

## Base obrigatória

Aplique apenas sobre o repositório `jorgemartim/leaphub-home-assistant` cuja árvore corresponda aos Git blobs de `BASE-GIT-BLOBS.txt`.

Validação da base:

```bash
bash verificar-base.sh /caminho/do/leaphub-home-assistant
```

Se qualquer arquivo aparecer como `DIVERGENTE`, **não aplique o patch**. Primeiro reconcilie a árvore real.

## Revisão antes da aplicação

```bash
cd /caminho/do/leaphub-home-assistant
git apply --check /caminho/GATEWAY-1.12.79.patch
```

Somente se o `--check` terminar sem erro:

```bash
git apply /caminho/GATEWAY-1.12.79.patch
cp /caminho/leaphub_gateway/tests/climate_c10_1_12_79_contract.py leaphub_gateway/tests/
python3 -m py_compile leaphub_gateway/connector.py
python3 leaphub_gateway/tests/climate_c10_1_12_79_contract.py
```

Depois disso, revise `git diff` e use o workflow existente do repositório para construir/publicar o add-on. Não copie o antigo ZIP de transformação para `leaphub_gateway/`.

## Ordem com o site

1. Gateway 1.12.79 primeiro.
2. Confirmar health e operação normal do Gateway.
3. Site Beta 1.12.352 depois.
4. Produção continua fora desta rodada.
