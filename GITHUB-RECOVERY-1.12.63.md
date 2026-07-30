# Recuperação GitHub — Gateway 1.12.63

1. Envie somente os arquivos de `CHANGED-FILES-1.12.63.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.63`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.62` até a imagem nova estar
   pública. A CI promoveu a 1.12.62 em `614e95c`; o commit da 1.12.63 não toca
   esse arquivo, então a promoção anterior fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile` nem a matriz de comandos. Ela corrige o
campo de onde a cortina do teto é lida.

**Causa, medida em campo (30/07/2026):** no C10/B10 o vidro do teto é fixo e o
único motor é o da cortina. A nuvem publica a posição dela em
`status.signal.1724`, entregue pela `leapmotor_api` como `security.roof_opening` —
que o connector consumia como teto solar. Cortina aberta: 100. Fechada: 0.
`sunshade_open` ficava nulo para sempre, e o matcher do comando não tinha o que
ler.

**Mudanças:**

- `connector.py` — em C10/B10, sem campo de cortina próprio,
  `security.roof_opening` alimenta `sunshade_position` e o teto fica nulo. A
  condição por modelo existe porque `rightList` declara o direito 160 mesmo em
  carro de vidro fixo.

**Migração:** nenhuma. Só muda a interpretação de um campo já existente. Reverter
para a 1.12.62 volta ao comportamento anterior sem perder dado.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada
pelo Home Assistant. Corrija a causa e execute novamente.
