# Leap Hub Gateway 1.12.56 — a falha de confirmação passa a dizer por quê

## Por que esta versão existe

O comando executa. O carro destrava. E o dono vê:

> A ação foi enviada, mas o novo estado não foi confirmado dentro da janela segura.

No log, só isto:

```
Janela rápida de <assinatura> encerrada após 5 leitura(s) sem confirmação conclusiva
```

Três causas muito diferentes produzem essa mesma linha, e não havia como distinguir:

1. O veículo-alvo não apareceu entre os dados retornados.
2. As amostras vieram, mas foram descartadas por serem anteriores ao comando.
3. As amostras foram avaliadas, mas o campo que o matcher consulta não veio na telemetria.

A terceira é a suspeita principal. Para `lock`/`unlock`, `_command_confirmation` lê `telemetry["locked"]`, que nasce em `connector.py` de `bool_or_none(attribute(status, "is_locked"))`. Se a biblioteca não expuser `is_locked` para o veículo, o campo fica nulo e toda leitura é inconclusiva — por mais leituras que se façam. É o mesmo padrão de `windows_open` e `sunshade`, que nunca confirmaram.

## O que mudou

Quando a janela se esgota sem confirmação, uma segunda linha explica:

```
Confirmação inconclusiva de unlock em <assinatura>: amostras avaliadas=5,
descartadas por idade=0, campos exigidos sem valor=[locked=ausente],
chaves presentes na telemetria=[battery_percent, charging_status, doors, ...]
```

- **`campos exigidos sem valor`** distingue `ausente` (a chave não existe), `nulo` (existe e veio `None`) e `vazio` (dicionário sem itens, o caso de `windows`). São defeitos diferentes, com correções diferentes.
- **`chaves presentes`** mostra o que a telemetria realmente trouxe, o que revela na hora se o dado existe sob outro nome.
- **`amostras avaliadas` e `descartadas por idade`** separam a causa 3 das causas 1 e 2.

O mapa `COMMAND_CONFIRMATION_FIELDS` declara, por comando, quais campos o matcher consulta. Um contrato compara esse mapa com os comandos realmente tratados em `_command_confirmation` e falha nos dois sentidos — comando novo sem campo declarado, ou campo declarado para comando inexistente. Sem isso, o diagnóstico envelheceria em silêncio.

## Privacidade

Só nomes de chave e contadores são registrados. Nenhum valor de telemetria entra no log: a mesma leitura carrega localização e identificadores do veículo. Há contrato verificando que a chamada de log não recebe o dicionário nem seus valores.

## Sem alteração de comportamento

Esta versão só acrescenta registro. Não muda o critério de confirmação, não altera a janela FAST, não repete comandos físicos, não toca credenciais, OCPP, MQTT, schema, migrations ou dados existentes. `Dockerfile` intocado.

## O que fazer com o resultado

Dispare um `unlock` e leia a segunda linha:

- **`locked=ausente`** — a biblioteca não expõe `is_locked` para este veículo. A correção é mapear o sinal correto ou confirmar por outra evidência.
- **`locked=nulo`** — o atributo existe e vem vazio; defeito diferente, provavelmente de leitura da nuvem.
- **`descartadas por idade` alto** — o problema é a frescura da amostra, não o campo.
- **`amostras avaliadas=0` com o alvo visto** — nenhuma leitura passou pelo filtro de idade.
