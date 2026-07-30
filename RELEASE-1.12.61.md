# Leap Hub Gateway 1.12.61 — três horas de fuso

A 1.12.60 não consertou nada: ela mediu. Esta conserta, com o número que a medida
produziu.

## O número

Em produção, 30/07/2026, host em `-03:00`:

| comando | horário | atraso relatado |
|---|---|---|
| `sunshade_open` | 09:15:22 | 10739s |
| `sunshade_close` | 09:17:41 | 10740s |
| `windows_open` | 09:19:41 | 10777s |

Dois minutos entre cada comando. Se a amostra estivesse realmente velha e não
refrescasse, o atraso cresceria ~120s entre linhas. Cresceu 1s e 37s. Era
**deslocamento fixo de 3 horas**, não atraso.

E as chaves da telemetria, que a 1.12.60 passou a registrar, vieram cheias —
`locked`, `captured_at`, `climate_details`, 40 campos. A telemetria nunca esteve
vazia.

## A cadeia do defeito

1. A nuvem manda `collectTime` como `"AAAA-MM-DD HH:MM:SS"`, sem fuso.
2. A `leapmotor_api` faz `datetime.strptime(raw_ts, _DATETIME_FMT)` — datetime
   **ingênuo**. O `# noqa: DTZ007` no código dela é exatamente a supressão do
   aviso de "datetime sem fuso".
3. O connector fazia `value.isoformat()`, produzindo string sem offset.
4. `_command_sample_is_fresh` fazia `parsed.replace(tzinfo=timezone.utc)` —
   presumia UTC.

Num host em `-03:00`, presumir UTC lê o carimbo 3 horas mais cedo do que ele é.
Toda amostra virava "velha", nenhum matcher rodava, e nenhum comando podia ser
confirmado — nem `sunshade_open`/`sunshade_close`, que têm campo declarado em
`COMMAND_CONFIRMATION_FIELDS` e cuja ação o proprietário viu acontecer no carro.

**O site sempre esteve certo.** Ele lê o mesmo `captured_at` com `strtotime()`,
que interpreta string sem fuso no fuso do servidor. Por isso exibia "Há 4 min"
corretamente e a figura do carro trocava o selo do teto. Dois consumidores do
mesmo campo, um acertando e outro errando — e o que errava era o que decidia se o
comando havia funcionado.

## A correção

**Na origem.** `iso_timestamp()` anexa o fuso local quando o datetime é ingênuo, e
preserva o offset quando já existe. Carimbo ambíguo deixa de ser produzido.

**Na leitura.** Carimbo sem fuso é lido como hora local — coerente com o que o
site já fazia e com o que a medida provou. Frescura e atraso passaram a derivar de
um único `_command_sample_epoch()`; antes eram dois blocos de parsing duplicados,
livres para divergir.

**Guarda de direção.** `COMMAND_SAMPLE_FUTURE_TOLERANCE_SECONDS = 900`: amostra
mais de 15 minutos no futuro não confirma. É a proteção contra o erro simétrico —
se em algum ambiente o carimbo vier mesmo em UTC, presumi-lo local o jogaria ~3h à
frente, e confirmar com carimbo impossível seria pior que não confirmar. O
adiantamento pequeno que a nuvem realmente apresenta (~1 min, medido) continua
aceito, porque é normal e a amostra ainda serve.

A margem de 2s não mudou de valor. Mudou de lugar: de `parsed >= started - 2.0`
para `lag <= 2.0`, dentro do atraso já calculado.

## Contrato

`tests/test_command_sample_timezone_1_12_61.py` — 15 casos. Os que importam:

- o caso exato da produção (amostra sem fuso, ~60s antes do comando) passa a
  relatar ~60s em vez de 10739s;
- `parsed.replace(tzinfo=timezone.utc)` não pode reaparecer no motor;
- o parsing do carimbo existe em **um** lugar (conta as ocorrências);
- amostra 3h no futuro **não** confirma; adiantamento de 90s confirma;
- carimbo com fuso explícito, inclusive com `Z`, não é reinterpretado;
- carimbo inutilizável presume frescura, como antes — melhor avaliar do que
  descartar toda confirmação por falta de hora.

O teste monta o cenário a partir do offset local de quem o roda, então não depende
de rodar em `-03:00`.

Um check da 1.12.60 precisou mudar: ele afirmava a expressão literal
`command_started_at - 2.0`, que o refactor eliminou. Passou a aceitar as duas
formas — o que o contrato deve garantir é a margem existir e ficar visível, não
como ela é escrita. É a segunda vez nesta sequência que um contrato meu quebrou
por afirmar forma em vez de garantia.

## Sem alteração

Matriz de comandos, campos de confirmação e janela FAST idênticos. Nada em
credenciais, OCPP, MQTT, schema, migrations ou dados existentes. `Dockerfile`
intocado.

## O que esperar depois de instalar

Acione um comando com o carro respondendo. A confirmação deve concluir, e o botão
deve sair de "Abrindo…". Se ainda aparecer inconclusiva, o atraso relatado agora
será um número pequeno — e aí a causa é outra, não o fuso.

Segue pendente, do lado do site: o botão que gira para sempre quando a janela
esgota, e o seletor do preparar o carro com "Sem quente/frio" pré-selecionado.
