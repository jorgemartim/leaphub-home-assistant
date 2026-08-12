# Recuperação GitHub — Gateway 1.12.77

1. Envie somente os arquivos de `CHANGED-FILES-1.12.77.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.77`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.76` até a imagem nova estar
   pública. O commit da 1.12.77 não toca esse arquivo.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Uma única mudança de comportamento, em `leaphub_gateway/telemetry_engine.py`:
`interactive_seconds` passa a ser truncado por `INTERACTIVE_SECONDS_CEILING`
(6s, o degrau já provado da confirmação de comando), com piso de 5s ditado pelo
round-trip HTTPS medido. Nada muda na telemetria de fundo, na matriz de
comandos, no schema do add-on ou no Dockerfile.
