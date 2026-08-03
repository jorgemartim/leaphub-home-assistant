# Recuperação GitHub — Gateway 1.12.72

1. Envie somente os arquivos de `CHANGED-FILES-1.12.72.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.72`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.71` até a imagem nova estar
   pública. O commit da 1.12.72 não toca esse arquivo, então a promoção anterior
   fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`, a matriz de comandos, a cadência nem
o schema do add-on. Ela acrescenta uma leitura de diagnóstico read-only.

Três partes que andam juntas numa recuperação manual:

- `connector.py` ganha `DRIVING_RECORD_METHODS`, `describe_shape()` e
  `handle_driving_record()`, mais a ação `driving_record` no despacho.
- `connector_server.py` põe `/v1/vehicles/driving-record` na allowlist de POST
  **e** dentro do bloco da trava de conta. Aplicar só a allowlist deixa o
  diagnóstico competindo com um comando do dono.
- `describe_shape()` é a garantia de privacidade: ela devolve a FORMA e nunca o
  valor. Se ela sair, o diagnóstico passa a despejar o histórico do dono no
  retorno.

Nada depende de estado no disco: não há migração, e voltar para a 1.12.71
continua funcionando com as mesmas tabelas.
