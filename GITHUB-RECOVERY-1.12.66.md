# Recuperação GitHub — Gateway 1.12.66

1. Envie somente os arquivos de `CHANGED-FILES-1.12.66.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.66`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.65` até a imagem nova estar
   pública. O commit da 1.12.66 não toca esse arquivo, então a promoção
   anterior fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile` nem a matriz de comandos. Ela faz a
composição do desenho seguir a ordem dos prefixos numéricos do pacote oficial,
em vez de delegá-la a `leapmotor_api._build_layer_list()`.
