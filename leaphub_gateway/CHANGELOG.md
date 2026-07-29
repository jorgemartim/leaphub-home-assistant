## 1.12.58

Distribuição pré-compilada preservada, com publicação em duas fases.

### Paridade de comandos: teto solar, janela, limite e mídia

- **Teto solar** — `sunroof_open` e `sunroof_close` (comando 300, direito **160**). Não confundir com a cortina do teto, que é `sunshade_open`/`sunshade_close` e exige o direito **161**; são hardwares e direitos diferentes.
- **Janela em posição intermediária** — `windows_position` (230) aceita de 0 a 100. `windows_open` e `windows_close` continuam existindo como os extremos. Num B10 a escala nativa observada é 0-10, atuando só em 0/2/5/10: a nuvem aceita qualquer valor e o carro ignora o que não entende, então converter para a escala do modelo é decisão de quem chama.
- **Limite de velocidade** — `set_speed_limit` (510), em km/h.
- **Mídia** — `music` (270) e `video` (290), com operação em `play`, `pause`, `next` ou `previous`.
- Toda faixa é conferida no gateway. Valor fora do intervalo, ausente ou não numérico é recusado antes de qualquer ida à nuvem, em vez de gastar um comando para o carro rejeitar.
- A matriz estável vai de 33 para 39 comandos, mais 3 experimentais.

### Preparo do carro, sob confirmação explícita

- `prepare_car` (360) entra como **experimental**: exige confirmação explícita do proprietário, como o Sentinela.
- A biblioteca serializa um JSON livre neste comando e a forma do pacote do comando imediato não é documentada — só a do agendamento equivalente (361). Em vez de repassar o que o site mandar, o gateway monta um envelope **allow-listed**: climatização (mesmo vocabulário já usado em produção no `ac_switch`), aquecimento de volante e desembaçamento de retrovisores. Chave desconhecida não atravessa.
- `seat_setting` ficou de fora: a documentação diz apenas "por assento 3=aquecer, 13=ventilar, 0=desligar", sem nomear os campos. Aquecimento e ventilação de assento já têm comando próprio desde a 1.12.57.
- `SENTRY_COMMANDS` deixou de ser derivado da matriz experimental. Com um segundo experimental, derivar faria `prepare_car` herdar a sonda e os campos de diagnóstico que são só do Sentinela.

### Mantido da 1.12.57

- `send_destination` preenchendo o kwarg obrigatório `address_name` da `leapmotor_api` 0.3.2, sem o qual nenhum destino chegava ao carro.
- `seat_heat` (301) e `seat_ventilation` (370) recebendo posição de 1 a 6 e nível de 0 a 3. Posições, conforme a biblioteca: 1=dianteiro esquerdo, 2=passageiro, 3=motorista, 4=dianteiro direito, 5 e 6=traseiros.

### Sem alteração

- Nenhuma mudança em credenciais, OCPP, MQTT, schema, migrations ou dados existentes. O critério de confirmação e a janela FAST seguem iguais.
- Nenhum comando físico é repetido, e nenhum comando novo é enviado sozinho: todos saem apenas quando o proprietário os aciona, e apenas para o carro que declara o direito correspondente.
- Ficaram deliberadamente fora `autopark` (150) e `piloted_parking` (350), que movem o carro, além de FOTA (390/391/392), `on3` (410), `seat_adjust` (280) e `rear_seats` (470). Os motivos estão em `RELEASE-1.12.58.md`.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
