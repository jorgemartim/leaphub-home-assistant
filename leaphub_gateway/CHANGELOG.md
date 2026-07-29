## 1.12.56

Distribuição pré-compilada preservada, com publicação em duas fases.

### A falha de confirmação passa a dizer por quê

- Comandos executam e o dono vê "a ação foi enviada, mas o novo estado não foi confirmado dentro da janela segura". O log dizia apenas "sem confirmação conclusiva", sem separar três causas distintas: veículo-alvo ausente, amostras descartadas por idade, ou campo exigido pelo matcher fora da telemetria.
- Uma segunda linha passa a registrar amostras avaliadas, amostras descartadas por idade, os campos exigidos sem valor (distinguindo ausente, nulo e vazio) e as chaves realmente presentes na telemetria.
- O mapa `COMMAND_CONFIRMATION_FIELDS` declara os campos por comando, e um contrato o compara com os comandos tratados em `_command_confirmation` nos dois sentidos, para o diagnóstico não envelhecer em silêncio.
- Só nomes de chave e contadores são registrados. Nenhum valor de telemetria entra no log.

### Mantido da 1.12.55

- `engine_precheck_ms` quebrado em `auth_status_ms`, `engine_lock_wait_ms` e `subscription_read_ms`, medido em campo caindo de 135718ms para 1ms.
- Teto de 20s na aquisição da trava global do motor no caminho do comando, com falha transitória 503 que preserva o comando na fila.

### Sem alteração

- Esta versão só acrescenta registro. Não muda o critério de confirmação nem a janela FAST, não repete comandos físicos e não altera credenciais, OCPP, MQTT, schema, migrations ou dados existentes.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
