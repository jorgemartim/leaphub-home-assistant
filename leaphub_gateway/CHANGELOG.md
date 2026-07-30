## 1.12.62

Distribuição pré-compilada preservada, com publicação em duas fases.

### Comando concorrente deixa de ser esquecido

Dois comandos seguidos na mesma assinatura: o segundo apagava o primeiro. Em
produção, 30/07/2026, `sunshade_open` às 13:34:40 e `unlock` às 13:36:03; a janela
fechou às 13:37:38 relatando **só** o `unlock`. Nenhuma linha sobre o
`sunshade_open` — nem confirmado, nem inconclusivo. O botão correspondente, no
site, continuou girando à espera de um veredito que nunca seria emitido.

- **Causa:** a janela de confirmação morava em colunas únicas da linha da
  assinatura (`command_key`, `command_vehicle_id`, `command_context_json`,
  `command_started_at`). Um segundo comando com chave diferente não é a mesma
  janela e sobrescrevia essas colunas, zerando a contagem de leituras. O contexto
  que o matcher usaria para julgar o primeiro deixava de existir.
- **Correção:** tabela nova e aditiva `command_confirmations`, com uma espera por
  `request_id` — hora de partida, contexto, prazo e contagem próprios. Cada
  leitura de telemetria é confrontada com todas as esperas pendentes.
- Repetir o boost do mesmo comando continua reaproveitando a espera; o site o
  repete como sinal de recuperação, e criar outra reiniciaria a contagem.
- A leitura passa a cobrir o veículo-alvo de todas as esperas, não só o do último
  comando.
- Janela em voo durante a atualização é adotada da linha antiga, com a hora de
  partida original.
- Espera abandonada é encerrada por prazo em vez de sobreviver consumindo ciclos.

### A janela usa os 180s que ela tem

`command_max_polls=5` esgotava a confirmação em ~112s com a cadência
`12, 20, 35, 45, 60, ...`, embora `command_until` dê 180s. O `unlock` do mesmo dia
teve uma amostra a +89s e foi declarado inconclusivo com quase um minuto de janela
por usar — carro acordando não cabia no orçamento.

- Quem encerra a espera passa a ser o prazo; a contagem de leituras virou teto de
  segurança contra cadência encurtada por configuração.
- Piso de 8 leituras, que cobre os 180s inteiros. `COMMAND_MAX_POLLS_FLOOR` e
  `COMMAND_MAX_POLLS_CEILING` são a fonte única lida pelo `gateway_manager` e
  pelos contratos.

### Diagnóstico

- `/status` informa `pending_confirmations`, com uma linha por espera (comando,
  `request_id`, leituras gastas, tempo restante) e as últimas resolvidas.
- O log de confirmação passou a ser por comando, dizendo se fechou por prazo ou
  por orçamento.

### Sem alteração

- A matriz de comandos, o conjunto de campos de confirmação e a regra de frescura
  seguem idênticos. A margem de 2s não mudou.
- Nenhuma mudança em credenciais, OCPP, MQTT ou dados existentes. A tabela nova é
  criada com `CREATE TABLE IF NOT EXISTS` e nenhuma coluna foi removida: reverter
  para a 1.12.61 volta a funcionar com a janela única, sem perder dado.
- `Dockerfile` intocado. Distribuição continua pré-compilada via GHCR, com
  promoção somente após validação pública da imagem.
