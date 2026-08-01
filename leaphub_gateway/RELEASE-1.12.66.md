## 1.12.66

Distribuição pré-compilada preservada, com publicação em duas fases.

### A ordem das camadas passa a vir do pacote oficial

Relato do proprietário em 01/08/2026, com dois recortes da tela: *"são duas
coisas, a porta e o porta-malas está sobrepondo o carro"*.

Os dois defeitos nascem na mesma função de terceiro,
`leapmotor_api.image._build_layer_list()` (pinada em `leapmotor-api==0.3.2`).
A ordem canônica está nos prefixos numéricos dos arquivos do pacote:

    01 tailgate_open   02 body                03 leftbehind_window_close
    04 leftfront_window_close                 05 tailgate_close
    06 hood_open       07 leftbehind_open     08 leftfront_open
    09 rightbehind_open                       10 rightfront_open

A biblioteca inverte **dois pares**:

- `carpic_tailgate_open` entra **depois** de `carpic_body` — a tampa do
  porta-malas é desenhada na frente do carro em vez de atrás dele.
- `carpic_*_window_close` entram **depois** das portas — o vidro e o caixilho
  da porta fechada são carimbados sobre a porta aberta.

As duas condições da porta são independentes na função: com a porta aberta e o
vidro fechado, as duas camadas entram, nessa ordem. Não havia guarda.

As camadas reais do C10 foram compostas nas duas ordens, lado a lado, e o
proprietário confirmou qual está certa antes de qualquer linha ser escrita.

### O remendo saiu

`_compose_official_frame()` tentava apagar o artefato do vidro **depois** da
composição: compunha a cena duas vezes e repintava um polígono de frações fixas
(`0.05`, `0.48`, `0.35`, `0.03`) derivado do retângulo da diferença. Havia
guarda para "pouco demais" e nenhuma para "demais".

Com o vidro empilhado atrás da porta não há artefato para apagar. A função
passa a montar a pilha ela mesma, por `official_layer_stack()` — pura, sem
imagem, exercitada por contrato. Se a composição por camadas falhar, ela cai
para `package.compose()` e registra o motivo.

### Descobertas do pacote

- O pacote **não tem** `hood_close`, `leftfront_close`, `rightfront_close`,
  `leftbehind_close` nem `rightbehind_close`. O corpo já vem fechado, e só o
  que abre tem sobreposição. A biblioteca pedia essas cinco camadas
  inexistentes, e `_composite_layers` as ignorava em silêncio.
- **`carpic_hood_open` existe** e compõe corretamente — a biblioteca nunca a
  pede, com o comentário *"Hood (no API status, always closed)"*. O gancho fica
  pronto em `official_layer_stack(hood_open=…)`, desligado por padrão: hoje o
  vocabulário da telemetria tem cinco aberturas (`front_left`, `front_right`,
  `rear_left`, `rear_right`, `trunk`) e o capô não é uma delas.

### Sem efeito colateral

- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- Cadência, confirmação de comando e prioridade do comando manual intocadas.
- `Dockerfile` intocado. Distribuição continua pré-compilada via GHCR, com
  promoção somente após validação pública da imagem.
