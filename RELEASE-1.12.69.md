## 1.12.69

Distribuição pré-compilada preservada, com publicação em duas fases.

### A cortina do teto aceita uma posição

Pedido do proprietário: "liberar tudo de janelas e cortinas". A janela já era
posicionável ponta a ponta (`windows_position`, cmd 230) e ganhou tela no site
1.12.296. A cortina não: a biblioteca aceita posição no mesmo cmd 161 dos
extremos, mas o `COMMAND_METHODS` mapeava apenas `open_sunshade`/`close_sunshade`
e **não passava `value`** — só abrir e fechar, nada no meio.

`sunshade_position` entra na matriz **estável**, com o direito 161, o mesmo de
`sunshade_open`/`sunshade_close`, e é anunciado para o carro que o declara.

### A escala não é a mesma dos dois lados

Este é o único comando desta matriz em que a escala de **leitura** e a de
**escrita** não coincidem, e é a parte da release que exige cuidado:

- **Leitura, 0-100.** No C10 e no B10 a nuvem publica a abertura da cortina em
  `security.roof_opening`, um percentual — medido no carro do proprietário em
  30/07/2026, nos dois sentidos: aberta 100, fechada 0. É o número que o gateway
  entrega como `sunshade_percent` e que o dono lê na figura do carro,
  "CORT. 45%".
- **Escrita, 0-10.** `leapmotor_api.models.SunshadeValue` documenta a faixa 0-10,
  com `OPEN = "10"` e `CLOSE = "0"` — onze degraus de 10%.

O gateway recebe **0-100**, para falar a mesma língua do site e de quem está
olhando a tela, e converte antes de chamar a biblioteca. Sem a conversão o carro
receberia um valor fora da faixa que ele declara aceitar, e o erro seria
silencioso: a nuvem responde `code=0` de qualquer maneira e o carro ignora o que
não entende — o dono pediria 45% e nada aconteceria, sem mensagem nenhuma.

O arredondamento é ao degrau mais próximo, **meio para cima**: 45% vira 5 (50%).
O `round()` do Python é meio para o par (`round(4.5)` dá 4 e `round(5.5)` dá 6),
o que faria a cortina descer num pedido e subir no outro sem regra visível para
quem pediu.

### O contrato

`test_sunshade_position_1_12_69` **exercita** `execute_vehicle_command` com um
dublê que registra o que chegaria à biblioteca, em vez de procurar a linha que
faz a conversão. Ele afirma os extremos que a biblioteca nomeia (0 → "0",
100 → "10"), o arredondamento nos dois lados do meio, e que **nenhuma entrada
válida de 0 a 100 produz valor fora de 0-10**. O controle negativo é o próprio
`windows_position`: ele continua mandando a porcentagem crua, porque a janela é
0-100 na biblioteca, e a cortina não pode fazer o mesmo.

Um contrato a mais guarda a premissa: se a troca da 1.12.63 sair — a que faz
`security.roof_opening` alimentar a cortina no C10/B10 —, a leitura muda de
origem e possivelmente de escala, e a conversão desta release vira erro em vez de
conserto. O teste falha antes, dizendo onde olhar.

### Sem efeito colateral

- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- `sunshade_open` e `sunshade_close` seguem exatamente como estavam; o comando
  novo é adicional.
- Nada entra em `COMMAND_CONFIRMATION_FIELDS`: comando de posição não se
  confirma por estado booleano, como já acontece com `windows_position`.
- Cadência e confirmação de comando intocadas.
- `Dockerfile` intocado.
