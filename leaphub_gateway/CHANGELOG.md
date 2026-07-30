## 1.12.59

Distribuição pré-compilada preservada, com publicação em duas fases.

### O resto da superfície da biblioteca, sob liberação por proprietário

Nove comandos passam a existir no gateway, todos no **gate experimental** — o mesmo do Sentinela. Ficam fechados até um administrador liberar o recurso para um proprietário específico, e ainda exigem confirmação explícita de quem aciona.

- **Estacionamento remoto** — `autopark` (150) e `piloted_parking` (350).
- **Atualização de firmware** — `fota_download` (390), `fota_install` (391) e `fota_schedule` (392), este último com data e hora.
- **Ajuste de assento** — `seat_adjust` (280).
- **Bancos traseiros** — `rear_seats` (470), só C16.
- **Modo ON3** — `on3_on` e `on3_off` (410). O comando tem código de direito próprio (`VehicleRight.ON3`), embora a biblioteca não descreva o que o modo faz além de "domestic models".

A matriz estável segue com 39 comandos; os experimentais vão de 3 para 12.

### Trava própria para o que move o carro

`autopark` e `piloted_parking` exigem, além da confirmação experimental, um reconhecimento próprio (`motion_acknowledged`): quem aciona declara que está junto do carro e com ele à vista. Nenhum aplicativo consegue verificar isso — o que ele pode fazer é não deixar acontecer por distração, e registrar que foi declarado.

### Pacote sem vocabulário documentado não vira túnel

`seat_adjust` e `piloted_parking` são declarados na biblioteca apenas como "the full JSON payload string": não existe lista de campos para validar por significado. Em vez de repassar o que vier do site, o gateway confere a **forma** — precisa ser um objeto, no máximo 12 chaves de nome plausível, valores escalares (ou um único nível de objeto, com até 8 subcampos), texto de até 120 caracteres e 512 bytes no total. Lista, aninhamento fundo, chave com nome estranho e valor de tipo inesperado são recusados.

Isto não valida se o comando faz sentido para o carro; garante que o gateway não se torne um caminho para conteúdo arbitrário até a nuvem. É exatamente por isso que estes dois exigem liberação por proprietário.

### FOTA não sai com dado inventado

`task_id` vem da listagem de tarefas da nuvem e é obrigatório — o gateway recusa ausente, zero e negativo em vez de mandar um número inválido e receber uma recusa opaca. O agendamento exige `AAAA-MM-DD HH:MM:SS` e uma data que exista (`2026-02-30` é recusada).

### Mantido da 1.12.58

- Teto solar (300, direito 160 — distinto da cortina do teto, 161), `windows_position` (230) de 0 a 100, `set_speed_limit` (510) e `music`/`video` (270/290).
- `prepare_car` (360) no gate experimental, com envelope allow-listed montado no gateway.
- `SENTRY_COMMANDS` como conjunto explícito, para que os experimentais novos não herdem a sonda de diagnóstico do Sentinela.

### Sem alteração

- Nenhuma mudança em credenciais, OCPP, MQTT, schema, migrations ou dados existentes. O critério de confirmação e a janela FAST seguem iguais.
- Nenhum comando físico é repetido e nenhum comando novo é enviado sozinho: todos saem apenas quando o proprietário os aciona, apenas para o carro que declara o direito correspondente, e apenas se o recurso estiver liberado para aquela conta.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
