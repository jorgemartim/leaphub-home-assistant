# Leap Hub Gateway 1.12.63 — a cortina do teto lê o campo que é dela

A 1.12.62 fez todo comando receber veredito. Este dá ao veredito da cortina algo
que ele possa ler.

## A medida

Diagnóstico do site (1.12.267), no C10 do proprietário, com a cortina acionada
no próprio carro e depois desfeita:

| | cortina aberta | cortina fechada |
|---|---|---|
| `cloud_raw_redacted.status.signal.1724` | **100** | **0** |
| `roof_open_percent` | 100 | 0 |
| `sunshade_open` / `sunshade_percent` | null | null |

O vidro do teto do C10 e do B10 é **fixo**: o único motor é o da cortina. A nuvem
publica a posição dela no signal 1724, a `leapmotor_api` entrega isso como
`security.roof_opening`, e o connector consumia como teto solar
([connector.py:2315](leaphub_gateway/connector.py:2315)).

## O candidato errado, e o que o descartou

Na primeira leitura o topo do ranking era o `signal.1256`, que foi de 0 para 1
junto com a abertura. Ele **não voltou a 0** quando a cortina fechou: reagia ao
carro acordar — a mesma amostra trouxe `ignition_details.on1: false → true`,
esperado com o dono dentro do carro.

Um único experimento teria trocado o mapeamento pela chave errada. Foi desfazer a
ação e reler que separou os dois. O contrato desta release afirma o comportamento
nos **dois** sentidos por esse motivo, e não por simetria estética.

Também vale registrar: a busca automática de candidatos priorizava sinais
binários, e a cortina é um percentual. Sem o `roof_open_percent` do lado
normalizado servindo de âncora, o 1724 teria passado despercebido.

## A correção

Em C10/B10, quando não existe campo de cortina próprio, `security.roof_opening`
passa a alimentar a cortina e o teto fica nulo em vez de mentir.

Três coisas se consertam de uma vez:

- a figura do carro acende o selo **CORT**, não o **TETO**;
- `sunshade_open` vira booleano de verdade, e o site consegue reconciliar o botão;
- `COMMAND_CONFIRMATION_FIELDS` de `sunshade_open`/`sunshade_close` passa a ter o
  que ler — o comando executa no carro e agora a tela conclui sozinha.

A troca é condicionada ao modelo de propósito: `vehicle.rightList` declara o
direito **160** (teto solar) mesmo nesses carros de vidro fixo. O direito não
prova o mecanismo, então um modelo com teto deslizante de verdade, ou um carro
que publique os dois campos, continua com cada valor no seu lugar.

## Sem alteração

- Os comandos seguem distintos: cortina é o direito 161, teto solar é o 160.
- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- `Dockerfile` intocado. Distribuição pré-compilada via GHCR, com promoção
  somente após validação pública da imagem.

## O que esta release não resolve

O inventário dos campos de confirmação do mesmo carro mostrou outras lacunas, que
ficam para a próxima:

- `climate_details.battery_preheat` **não vem** na telemetria → `battery_preheat_on/off`
  não tem como ser confirmado;
- `charge_limit_percent` vem nulo → `set_charge_limit` idem;
- `rightList` do carro **não inclui o direito 193**, então `start_charging` e
  `stop_charging` não são suportados nele;
- os campos de banco e volante (`seat_comfort.*`) e de janela (`windows.*`)
  **existem** e estão preenchidos, então a falha relatada nesses comandos é de
  execução, não de confirmação — precisa do histórico de respostas da nuvem para
  ser diagnosticada.
