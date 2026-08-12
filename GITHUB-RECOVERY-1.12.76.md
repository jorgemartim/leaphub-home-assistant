# Recuperação GitHub — Gateway 1.12.76

1. Envie somente os arquivos de `CHANGED-FILES-1.12.76.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.76`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.75` até a imagem nova estar
   pública. O commit da 1.12.76 não toca esse arquivo.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Uma única mudança de comportamento, em `leaphub_gateway/telemetry_engine.py`:
`_settled_confirmation` passa a aceitar `request_id` e a filtrar por ele quando
existe, e `_register_confirmation` deixa de restringir a guarda ao caso anônimo.

**Por que não podia sair como 1.12.75:** aquela versão já foi publicada e
promovida (`config.yaml` em `1.12.75` na `main`). Um segundo commit sob o mesmo
número tentaria republicar uma imagem que já existe.
