# Leap Hub Gateway 1.12.58 — paridade de comandos

A 1.12.57 entregou o conserto do envio de destino e o conforto de assento. Esta versão
continua o mesmo trabalho: mais quatro funções do carro que a nuvem já aceitava e o
gateway não expunha, mais o preparo do carro sob confirmação.

## Seis comandos novos

| comando | cmd | direito | parâmetros |
|---|---|---|---|
| `sunroof_open` / `sunroof_close` | 300 | **160** | — |
| `windows_position` | 230 | 230 | 0-100 |
| `set_speed_limit` | 510 | 510 | km/h |
| `music` | 270 | 270 | play/pause/next/previous |
| `video` | 290 | 290 | play/pause/next/previous |

**Teto solar não é a cortina do teto.** `sunroof_*` é o comando 300 com o direito
**160**; `sunshade_*`, que já existia, exige o direito **161**. São hardwares distintos,
e trocar os dois faria o comando aparecer para quem não tem o hardware e sumir para quem
tem. Há contrato afirmando os quatro códigos, justamente porque é o par mais fácil de
confundir.

**Janela intermediária.** `windows_position` aceita 0-100 no C10, e é o mesmo comando
230 que `windows_open`/`windows_close` usam nos extremos. Num B10 a escala nativa
observada é 0-10, atuando só em `0/2/5/10`: a nuvem responde `code=0` para qualquer
valor e o carro ignora o que não entende. Converter para a escala do modelo é decisão de
quem chama; o gateway valida 0-100 e não inventa conversão.

**Faixa conferida no gateway.** Posição de janela, limite de velocidade e operação de
mídia são validados antes do despacho. Um comando gasto para o carro rejeitar é uma ida
à nuvem, um registro na fila e uma espera do dono, tudo por um valor que já dava para
recusar aqui.

**Capacidade.** Todo comando novo declara o direito que exige, então o anúncio segue o
filtro existente: só aparece para o carro que tem o direito. Sem dados de capacidade o
fail-open é preservado e nada é escondido de quem já funciona.

A matriz estável vai de 33 para 39 comandos, mais 3 experimentais.

## `prepare_car`, sob confirmação explícita

`prepare_car` (360) entra na matriz **experimental** — exige confirmação explícita do
proprietário, como o Sentinela.

A razão é a forma do pacote. A biblioteca o expõe como
`prepare_car(vin, *, params: dict)` e serializa o dicionário sem validar nada: o
`cmd_content` é "the full JSON payload string". A estrutura desse pacote está
documentada para o **agendamento** (`361`) — `air_condition`, `seat_setting`,
`steeringWheelHeatCtrl`, `rearMirrorHeating`, `syn_path` — mas não para o comando
imediato.

Duas decisões saem disso:

1. **O envelope é montado aqui, allow-listed.** Nada que o site mande atravessa:
   `prepare_car_parameters()` constrói o pacote a partir de parâmetros nomeados e só com
   as dimensões que o proprietário pediu. O vocabulário de `air_condition` é o mesmo que
   `climate_close_parameters()` já usa em produção no `ac_switch`
   (`circle`/`mode`/`operate`/`position`/`temperature`/`windlevel`/`wshld`), conferido
   contra os enums da biblioteca. Temperatura 16-32, ventilação 1-7, volante 0-3.
2. **`seat_setting` ficou de fora.** A documentação diz apenas "por assento 3=aquecer,
   13=ventilar, 0=desligar", sem nomear os campos de cada assento. Aquecimento e
   ventilação de assento já têm comando próprio desde a 1.12.57, com faixa conhecida —
   não há motivo para adivinhar um segundo caminho para a mesma função.

`SENTRY_COMMANDS` deixou de ser derivado de `EXPERIMENTAL_COMMAND_METHODS`. Com um
segundo experimental, derivar faria `prepare_car` herdar a sonda e os campos de
diagnóstico que são só do Sentinela. O contrato que afirmava a linha literal passou a
afirmar o conteúdo do conjunto, mais um guarda contra voltar à forma derivada.

## O que ficou fora, e por quê

- **`autopark` (150) e `piloted_parking` (350)** movem o carro por comando remoto. Expor
  isso a partir de um aplicativo web exigiria garantias de presença e de campo de visão
  que o aplicativo não tem como dar. Ficam fora enquanto essa garantia não existir — não
  é limitação técnica, é escolha.
- **FOTA (`390`/`391`/`392`)** instala firmware e depende de um `task_id` vindo de uma
  listagem de tarefas que ainda não existe no gateway. Expor `install` sem a listagem
  seria oferecer um botão sem o dado que ele precisa.
- **`on3` (410)** não tem semântica documentada nem código de direito na tabela
  `VehicleRight` — não há como descrever ao dono o que o botão faz, nem filtrar por
  capacidade.
- **`seat_adjust` (280)** recebe dicionário livre e, ao contrário de `prepare_car`, não
  tem agendamento equivalente de onde aprender a forma.
- **`rear_seats` (470)** é só C16, e o formato de `seat_info` não é documentado.
- **Agendamentos** (`171` climatização, `361` preparo, e o de carga) são um recurso à
  parte: precisam de listar, editar e cancelar, não de um botão. O `getAppointment` já
  está mapeado para quando isso for feito.

## Contratos

`tests/test_command_parity_1_12_58.py` cobre: os seis comandos novos na matriz estável
com seus direitos, `prepare_car` no gate experimental e recusado sem confirmação, os
quatro códigos de teto solar e cortina, cada valor fora de faixa recusado **sem que nada
chegue à nuvem**, o envelope do `prepare_car` montado só com as dimensões pedidas e sem
repassar chave desconhecida, e o anúncio filtrado por capacidade ponta a ponta pela
serialização.

`tests/test_seat_comfort_1_12_57.py` continua valendo sem uma linha alterada: ele afirma
`versão >= 1.12.57`, não igualdade. Foi o único contrato que este bump não precisou
tocar — os outros 43 arquivos mudaram só porque fixam a versão exata.

## Sem alteração

Nada em credenciais, OCPP, MQTT, schema, migrations ou dados existentes. O critério de
confirmação e a janela FAST seguem iguais; os comandos novos não entram no
`COMMAND_CONFIRMATION_FIELDS`, porque confirmar janela ou mídia exigiria saber a que
campo de telemetria cada um corresponde, e declarar um mapeamento adivinhado produziria
confirmação falsa — o oposto do que o diagnóstico da 1.12.56 foi buscar. Eles valem pelo
aceite do envio, como os outros comandos sem matcher.

`Dockerfile` intocado.
