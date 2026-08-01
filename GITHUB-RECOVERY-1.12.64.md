# Recuperação GitHub — Gateway 1.12.64

1. Envie somente os arquivos de `CHANGED-FILES-1.12.64.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.64`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.63` até a imagem nova estar
   pública. A CI promoveu a 1.12.63 em `422476f`; o commit da 1.12.64 não toca
   esse arquivo, então a promoção anterior fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile` nem a matriz de comandos. Ela faz o
desenho do veículo acompanhar a mudança de estado sem depender de um comando
manual.
