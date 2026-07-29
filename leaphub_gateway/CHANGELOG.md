## 1.12.57

Distribuição pré-compilada preservada, com publicação em duas fases.

### Enviar destino ao carro volta a funcionar

- O comando falhava sempre, com `Parâmetro de destino ainda não suportado pela biblioteca: address_name` no log e nenhuma requisição saindo do gateway.
- A `leapmotor_api` 0.3.2 declara `send_destination(vin, *, address, address_name, latitude, longitude)`. O `address_name` é obrigatório e não tinha valor no mapa que alimenta a introspecção de assinatura, então um parâmetro exigido era tratado como não suportado.
- O nome do destino passa a preencher `address_name`, do mesmo modo que já preenchia `name`, `title` e `poi_name`. A validação de coordenadas continua igual.

### Conforto de assento por comando remoto

- A matriz estável ganha `seat_heat` (direito 301) e `seat_ventilation` (direito 370), os dois primeiros comandos estáveis que recebem parâmetro: posição de 1 a 6 e nível de 0 a 3, passados por palavra-chave como a biblioteca exige.
- Faixa conferida no gateway. Posição ou nível fora do intervalo, ausente ou não numérico é recusado antes de qualquer ida à nuvem, em vez de gastar um comando para o carro rejeitar.
- O anúncio segue o filtro de capacidade: só aparece para o carro que declara o direito, ou para todos quando a nuvem não informa capacidade (fail-open preservado). As flags de hardware 14 → 301 e 42/43 → 370 continuam sendo expandidas.
- A matriz vai de 31 para 33 comandos estáveis, mais os 2 experimentais.

### Mantido da 1.12.56

- Diagnóstico de confirmação inconclusiva separando as três causas: veículo-alvo ausente, amostras descartadas por idade e campo exigido fora da telemetria.
- `engine_precheck_ms` quebrado em `auth_status_ms`, `engine_lock_wait_ms` e `subscription_read_ms`, e teto de 20s na aquisição da trava global do motor no caminho do comando.

### Sem alteração

- Nenhuma mudança em credenciais, OCPP, MQTT, schema, migrations ou dados existentes. O critério de confirmação e a janela FAST seguem iguais.
- Nenhum comando físico é repetido. Os comandos novos só são enviados quando o proprietário os aciona.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
