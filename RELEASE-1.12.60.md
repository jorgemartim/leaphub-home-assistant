# Leap Hub Gateway 1.12.60 — medir antes de corrigir

Esta release não conserta a confirmação de comando. Ela conserta o **instrumento**
que devia explicar por que a confirmação falha, e que estava dando a resposta
errada — errada o suficiente para me levar a duas conclusões falsas.

## O defeito da instrumentação

A 1.12.56 introduziu esta linha de diagnóstico:

```
Confirmação inconclusiva de sunshade_open em acct_…: amostras avaliadas=0,
descartadas por idade=1, campos exigidos sem valor=[nenhum],
chaves presentes na telemetria=[nenhuma].
```

`chaves presentes na telemetria=[nenhuma]` parece dizer que o carro não reportou
nada. Não é o que diz. A atribuição estava assim:

```python
if not self._command_sample_is_fresh(telemetry, command_started):
    command_stale_samples += 1
    continue                      # <- amostra velha sai por aqui
command_evaluated_samples += 1
matched, evaluable = self._command_confirmation(...)
if not evaluable:
    command_available_keys = sorted(telemetry.keys())[:40]   # <- só aqui
```

A lista só era preenchida para amostra que **passou** na frescura e ainda assim
saiu inconclusiva. Com `amostras avaliadas=0`, nenhuma passou — então a lista
nunca foi tocada e ficou vazia por omissão, não por observação.

Corrigido: as chaves são registradas para qualquer amostra do veículo-alvo, antes
do descarte por idade. `[nenhuma]` volta a significar telemetria sem chave.

## O que faltava medir

`descartadas por idade=1` diz que a amostra é velha. Não diz **quanto**. Três
segundos de folga curta e três horas de carro parado produzem a mesma linha, e
exigem correções opostas.

`_command_sample_lag()` calcula `command_started_at - captured_at` e a linha passa
a trazer `amostra mais recente 3600s antes do comando`. Devolve `None` — e a linha
diz `sem carimbo de hora` — quando não há como comparar, os mesmos casos em que
`_command_sample_is_fresh` presume frescura.

## O que o teste do proprietário eliminou

Em 30/07/2026, com o carro dormindo, o proprietário abriu a cortina do teto pelo
Leap Hub: **o carro acordou e a cortina abriu**. Com o carro acordado, fechou
também. Em nenhum dos dois casos a tela concluiu.

Isso derrubou duas hipóteses que eu havia registrado como causa:

- **"Sem método de wake, o comando não chega a um carro dormindo."** A nuvem
  acorda o carro ao receber o comando. O `despertar_real=False` de todos os logs
  significa apenas que o *gateway* não fez wake explícito — a biblioteca
  `leapmotor-api` 0.3.2 não expõe nenhum, e não precisa expor.
- **"A telemetria chega vazia."** Era o defeito de instrumentação acima.

Sobrou uma causa, e ela é medível: em todos os comandos, inclusive nos que
executaram fisicamente, `amostras avaliadas=0`. O portão

```
captured_at >= command_started_at - 2.0
```

rejeita 100% das amostras, então nenhum matcher roda. Não é matcher faltando:
`sunshade_open` e `sunshade_close` estão entre os 24 comandos com campo declarado
em `COMMAND_CONFIRMATION_FIELDS`.

Esta release não altera o portão de propósito. Alterá-lo agora seria escolher
entre duas correções sem saber qual: alargar a margem (se o desalinhamento é de
segundos) ou parar de tratar `captured_at` como momento da captura (se é de horas).
O próximo log responde.

## Contrato

`tests/test_command_sample_lag_1_12_60.py` afirma, por posição no código, que a
captura das chaves acontece **antes** do descarte por idade e **fora** do ramo
`if not evaluable` — é a regressão exata que produziu o diagnóstico falso. Também
guarda o matcher de `sunshade_*` e `windows_*`, que executam de fato no carro e
sem os quais não há via de confirmação, e mantém visível a margem de 2s.

## Sem alteração

A matriz de comandos, o critério de confirmação e a janela FAST seguem idênticos.
Nada em credenciais, OCPP, MQTT, schema, migrations ou dados existentes. Esta
release só mede. `Dockerfile` intocado.

## O que vem depois, na ordem

1. Instalar e acionar um comando qualquer. A linha de confirmação inconclusiva
   vai trazer o atraso.
2. Corrigir o portão conforme o número: margem, fuso/parse, ou origem do
   `captured_at`.
3. Só então mexer na mensagem do site — que aí pode dizer "confirmado" de
   verdade, em vez de escolher entre dois textos imprecisos. Hoje o aplicativo
   acusa falha em comando que funcionou, e é isso que o proprietário sente.
