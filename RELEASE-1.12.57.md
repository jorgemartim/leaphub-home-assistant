# Leap Hub Gateway 1.12.57 — o destino nunca saía, e os assentos não existiam

## Por que esta versão existe

Duas coisas, encontradas no log de campo de 29/07/2026.

### 1. `send_destination` falhava sempre

```
Comando remoto em segundo plano falhou (RuntimeError):
Parâmetro de destino ainda não suportado pela biblioteca: address_name
```

Nenhuma requisição chegou à nuvem. O comando morria dentro do gateway.

A causa está na `leapmotor_api` 0.3.2:

```python
def send_destination(self, vin, *, address, address_name, latitude, longitude)
```

`address_name` é **keyword-only e sem valor padrão** — obrigatório. O `execute_vehicle_command`
monta a chamada por introspecção de assinatura: para cada parâmetro exposto pela biblioteca, procura
um valor no mapa `values`. Quando o parâmetro não está no mapa e também não tem padrão, ele conclui,
corretamente, que não sabe preenchê-lo, e recusa em vez de chamar errado.

O mapa trazia `name`, `title`, `poi_name` e `destination_name` — quatro apelidos para o nome do
destino — mas não `address_name`, que é justamente o nome que esta versão da biblioteca usa. O
resultado é que a proteção disparava contra um parâmetro que o gateway tinha em mãos.

A correção é preencher `address_name` com o mesmo nome do destino. A introspecção continua igual: é
ela que mantém o gateway compatível com versões da biblioteca que nomeiem o campo de outro jeito.
A validação de coordenadas (latitude -90..90, longitude -180..180) não mudou.

### 2. Aquecimento e ventilação de assento não existiam na matriz

A matriz de comandos só tinha comandos de argumento zero, mais `set_charge_limit` e
`send_destination`. Aquecimento (`301`) e ventilação (`370`) de assento ficaram de fora porque
exigem dois valores — posição e nível — e não havia caminho para eles.

A biblioteca declara:

```python
def seat_heat(self, vin, *, position: int, level: int)        # cmd 301, posição 1-6, nível 0-3
def seat_ventilation(self, vin, *, position: int, level: int)  # cmd 370
```

e codifica o par como `{"value": "posição,nível"}`.

## O que mudou

- `seat_heat` e `seat_ventilation` entram na **matriz estável**, com os direitos 301 e 370. São os
  dois primeiros comandos estáveis que recebem parâmetro, e por isso ganharam um conjunto próprio,
  `SEAT_COMFORT_COMMANDS`, em vez de virarem um caso especial escondido no meio do dispatch.
- A faixa é conferida **no gateway**: posição fora de 1-6, nível fora de 0-3, valor ausente ou não
  numérico é recusado antes de qualquer ida à nuvem. Um comando gasto para o carro rejeitar é uma
  ida à nuvem, um registro na fila e uma espera do dono, tudo por um valor que já dava para recusar.
- O anúncio respeita o filtro de capacidade introduzido antes: o comando só aparece para o carro que
  declara o direito. Sem dados de capacidade, o fail-open é preservado e nada é escondido de quem já
  funciona. As flags de hardware continuam expandidas — `14` implica `301`, `42` e `43` implicam `370`.
- A matriz vai de **31 para 33** comandos estáveis, mais os 2 experimentais.

## Contrato

`tests/test_seat_comfort_1_12_57.py` prova o par de garantias: os comandos estão na matriz estável
com os direitos certos, a posição e o nível chegam à biblioteca **por palavra-chave**, todo valor
fora de faixa é recusado sem que nada chegue à nuvem, o filtro de capacidade esconde o comando de
quem não tem o direito, e `send_destination` preenche `address_name` contra um dublê com a assinatura
real da 0.3.2.

O contrato afirma `versão >= 1.12.57`, nunca igualdade. Um contrato existe para provar que a garantia
introduzida ali não regrediu, não para carimbar em que release o repositório está — os que fixavam
versão exata quebravam sozinhos na release seguinte e escondiam, atrás de uma falha cosmética, as
verificações de comportamento que vinham depois.

## O que não mudou

- Nada em credenciais, OCPP, MQTT, schema, migrations ou dados existentes.
- O critério de confirmação e a janela FAST seguem iguais. Os comandos novos não entram no
  `COMMAND_CONFIRMATION_FIELDS`: confirmar assento exigiria saber a que campo de telemetria cada
  posição corresponde, e declarar um mapeamento adivinhado produziria confirmação falsa — o oposto
  do que o diagnóstico da 1.12.56 foi buscar. Eles se comportam como os outros comandos sem matcher:
  valem pelo aceite do envio.
- Nenhum comando físico é repetido, e nenhum é enviado sozinho. Os dois novos só saem quando o
  proprietário os aciona.
- `Dockerfile` intocado. Distribuição segue pré-compilada via GHCR, com promoção do `config.yaml`
  somente depois de a imagem estar pública.

## Fora do escopo, de propósito

`prepare_car` (`360`) foi avaliado e **deixado de fora**. A biblioteca o expõe como
`prepare_car(vin, *, params: dict)` e serializa o dicionário sem validar nada: o `cmd_content` é
"the full JSON payload string". A forma desse pacote está documentada para o **agendamento** (`361`)
— `air_condition`, `seat_setting`, `steeringWheelHeatCtrl`, `rearMirrorHeating`, `syn_path` — mas não
para o comando imediato. Publicar um payload plausível porém não confirmado entregaria ao dono um
botão que o carro recusa em silêncio, que é exatamente a classe de problema que as duas últimas
releases foram atacar. Fica pendente de uma captura de tráfego real do `remote/ctl`.
