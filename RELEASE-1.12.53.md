# Leap Hub Gateway 1.12.53 — a renovação de token que nunca era chamada

## Por que esta versão existe

`_try_refresh_client_session` tenta renovar a sessão da Leapmotor antes de recorrer ao
login completo. Ela procurava o método por três nomes:

```python
for method_name in ("refresh_session", "refresh_token", "refresh"):
```

O nome real na `leapmotor-api` é **`token_refresh`**. A documentação da biblioteca é explícita:
*"token refresh is handled automatically (…) see `token_refresh()` for manual control"*.

Como nenhum dos três aliases existe, `getattr` devolvia `None` para todos, a função saía sem
renovar nada e **toda sessão vencida caía direto no login completo** — de 5 a 18 s por conta,
medidos em campo. Com onze contas, isso é o pico de logins visto depois de cada reinício e a
cada expiração.

## Correção

`token_refresh` entra como primeiro alias da cadeia. A proteção contra multiplicar chamadas à
nuvem continua igual: a cadeia deduplica por identidade da função, para na primeira resposta
conclusiva e classifica exceções uma única vez.

Se a versão instalada da biblioteca não tiver o método, `getattr` devolve `None` e o
comportamento é exatamente o de antes. Risco zero de regressão.

## O que não mudou

Nada de comando físico, credencial, vínculo, OCPP, MQTT, schema ou migration. O keep-alive da
entrega da 1.12.52, a fila em WAL, o paralelismo de coleta e a confirmação FAST permanecem
como estavam.
