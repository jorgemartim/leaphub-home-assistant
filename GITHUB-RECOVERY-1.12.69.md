# Recuperação GitHub — Gateway 1.12.69

1. Envie somente os arquivos de `CHANGED-FILES-1.12.69.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.69`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.68` até a imagem nova estar
   pública. O commit da 1.12.69 não toca esse arquivo, então a promoção
   anterior fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`. Ela acrescenta um comando à matriz
estável: `sunshade_position` (cortina do teto numa posição intermediária, cmd
161, direito 161). `sunshade_open` e `sunshade_close` seguem inalterados.

A parte que exige atenção numa recuperação manual é a conversão de escala em
`execute_vehicle_command`: o gateway recebe 0-100 (a escala da leitura e do site)
e converte para os 0-10 que a biblioteca documenta. Aplicar a mudança pela
metade — o comando na matriz sem a conversão — faz o carro receber um valor fora
da faixa e ignorá-lo em silêncio.
