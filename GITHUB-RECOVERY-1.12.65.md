# Recuperação GitHub — Gateway 1.12.65

1. Envie somente os arquivos de `CHANGED-FILES-1.12.65.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.65`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.64` até a imagem nova estar
   pública. A CI promoveu a 1.12.64 em `60ac13b`; o commit da 1.12.65 não toca
   esse arquivo, então a promoção anterior fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile` nem a matriz de comandos. Ela faz a
cadência de leitura seguir o carro: quem teve atividade observada volta a ser
lido a cada 90s; só o veículo realmente parado cai para 600s.
