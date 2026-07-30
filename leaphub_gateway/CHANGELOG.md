## 1.12.60

Distribuição pré-compilada preservada, com publicação em duas fases.

### O diagnóstico da confirmação deixa de mentir

- A instrumentação da 1.12.56 registrava as chaves observadas na telemetria **dentro** do ramo `if not evaluable`, alcançável somente por amostra que sobrevive ao teste de frescura. Amostra velha caía no `continue` sem tocar a lista, e o log saía `chaves presentes na telemetria=[nenhuma]` — que se lê como "a telemetria veio vazia" quando o caso era apenas atraso.
- As chaves passam a ser registradas para **qualquer** amostra do veículo-alvo, velha ou não. `[nenhuma]` volta a significar o que diz.
- Novo `_command_sample_lag()`: a linha de confirmação inconclusiva informa a distância entre a captura da amostra e o envio do comando (`amostra mais recente 3600s antes do comando`). `descartadas por idade` sozinho não dizia se o carro estava 3 segundos ou 3 horas atrás — e é essa distância que separa "recebeu e não obedeceu" de "não reportou nada novo".

### Por que isto importa agora

Um teste do proprietário em 30/07/2026 mostrou a cortina do teto **abrindo e fechando de fato** pelo Leap Hub, com o carro dormindo antes do comando, e a tela não concluindo em nenhum dos dois casos. Isso descartou duas hipóteses: a nuvem acorda o carro sozinha ao receber o comando (o `despertar_real=False` diz apenas que o gateway não fez wake explícito, e a biblioteca não expõe nenhum), e a telemetria não vinha vazia.

O que restou é medível: em todos os comandos, inclusive os que executaram, o log traz `amostras avaliadas=0, descartadas por idade=1`. O portão de frescura (`captured_at >= command_started_at - 2.0`) rejeita 100% das amostras, então nenhum matcher chega a rodar — mesmo em `sunshade_open`/`sunshade_close`, que têm matcher declarado. Esta release não corrige o portão: ela instala o instrumento que diz se o desalinhamento é de segundos (margem curta, fuso ou parse) ou de horas (o `captured_at` da nuvem não é o momento da captura). São correções diferentes e o log anterior não distinguia.

### Mantido da 1.12.59

- Nove comandos no gate experimental, liberados por proprietário e um a um pelo administrador: `autopark`, `piloted_parking`, `seat_adjust`, `rear_seats`, `on3_on`/`on3_off` e FOTA `download`/`install`/`schedule`.
- `motion_acknowledged` nos dois que movimentam o veículo, e envelope allow-listed nos que têm pacote sem vocabulário documentado.

### Sem alteração

- Nenhuma mudança em credenciais, OCPP, MQTT, schema, migrations ou dados existentes. A matriz de comandos, o critério de confirmação e a janela FAST seguem exatamente iguais: esta release só mede.
- `Dockerfile` intocado. Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
