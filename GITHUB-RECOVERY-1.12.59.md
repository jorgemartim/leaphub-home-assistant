# Recuperação GitHub — Gateway 1.12.59

1. Envie somente os arquivos de `CHANGED-FILES-1.12.59.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.59`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.57` até a imagem nova estar pública.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`. Toda a mudança de comportamento está em
`connector.py`:

- Nove comandos entram no **gate experimental**, nunca na matriz estável: `autopark` (150),
  `piloted_parking` (350), `seat_adjust` (280), `rear_seats` (470), `on3_on`/`on3_off`
  (410) e FOTA `download`/`install`/`schedule` (390/391/392). Ficam fechados até um
  administrador liberar o recurso para um proprietário específico e ainda exigem
  confirmação explícita de quem aciona.
- `autopark` e `piloted_parking` exigem também `motion_acknowledged`, uma trava própria dos
  comandos que movem o carro.
- `seat_adjust` e `piloted_parking` têm pacote sem vocabulário documentado; o gateway
  confere a forma (objeto raso, chaves plausíveis, valores escalares, tetos de quantidade e
  tamanho) em vez de repassar o que vier.
- FOTA exige `task_id` válido, e o agendamento exige data e hora existentes.

Os experimentais vão de 3 para 12; a matriz estável segue com 39 comandos.

Nenhum comando físico é repetido e nenhum é enviado sozinho. O site ainda não oferece
estes controles — enquanto as chaves de recurso e o formulário do administrador não
existirem lá, os comandos ficam sem como ser acionados, o que é o estado seguro.

Se o workflow falhar antes da promoção, não altere manualmente a versão anunciada pelo
Home Assistant. Corrija a causa e execute novamente.
