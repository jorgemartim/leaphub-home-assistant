# Leap Hub Gateway 1.12.76

## Uma confirmação por comando, também quando o boost traz id

A 1.12.75 já está publicada e instalada. Esta release conserta o defeito que o
teste de campo do dia 12/08/2026 revelou **depois** dela — e que só existe porque
as duas correções anteriores se encontraram.

Medido em campo, conta `acct_1c8b987d`: **cinco dos seis comandos confirmaram
DUAS vezes com o mesmo `ref_`**, a segunda "após 1 leitura(s) e 0s", cerca de 45s
depois — a cadência do boost da tela.

```
08:13:35  unlock (ref_3cf916b9) confirmado ... após 3 leitura(s) e 11s
08:14:17  unlock (ref_3cf916b9) confirmado ... após 1 leitura(s) e  0s
```

A guarda `_settled_confirmation`, criada na 1.12.74, só valia para o boost
**anônimo** — porque naquele momento o site descartava o `request_id`. A 1.12.331
do site devolveu o id, e com isso o caso comum passou a ser o **identificado**,
que atravessava a guarda: caía no `INSERT OR REPLACE` de
`_register_confirmation`, reescrevia a linha já confirmada com `started_at` novo,
e ela reconfirmava na leitura seguinte porque o estado que procura já tinha sido
atingido.

A guarda agora é chaveada pela **identidade**: havendo `request_id`, procura-se o
veredito daquele id. Com identidade exata isto é seguro — um toque novo no botão
gera um `request_uuid` novo, logo um `confirmation_id` novo, e não é suprimido.

## O par de mutações

Voltar a guarda para "só anônimo" reprova o caso novo
(`test_a_repeated_boost_with_the_same_id_does_not_resurrect_the_verdict`);
ignorar o id de vez reprova o controle negativo
(`test_an_identified_boost_is_never_suppressed`). Necessário **e** não excessivo.

## Nada mais muda

Sem alteração no `Dockerfile`, na matriz de comandos, no schema do add-on, na
escada de cadência ou no orçamento de leituras — tudo isso é da 1.12.75, que já
está no ar.
