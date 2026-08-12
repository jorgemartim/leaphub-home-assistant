# Leap Hub Gateway 1.12.75

## O orçamento de leituras voltou a ser teto

A 1.12.74 adensou a escada de confirmação e manteve as mesmas 8 leituras. Com a
escada antiga a 8ª leitura caía aos 382s, muito além dos 180s da janela, e o
teto **nunca** encerrava a espera antes do prazo. Com a escada nova ela cai aos
195s — e basta **uma** leitura extra para o teto passar na frente do prazo.

Medido em campo em 11/08/2026 (conta `acct_1c8b987d`):

```
14:52:07  unlock  8 leituras,  135s  (orçamento de leituras esgotado)
14:53:02  unlock  8 leituras,   60s  (orçamento de leituras esgotado)
```

14:52:07 − 135s = 14:49:52 e 14:53:02 − 60s = 14:52:02: exatamente os instantes
em que os dois despachos de `unlock` terminaram. As duas janelas tinham 180s.

Leitura extra é comum porque a cadência acompanha a espera **mais nova**
(`min(poll_count)`) enquanto **cada** leitura consome o orçamento de **todas**
as pendentes: apertar um segundo botão reinicia a escada no primeiro degrau e
queima o resto do orçamento do comando anterior em segundos. Foi o que fizeram
`sunshade_open` às 14:50:58 e `sunshade_close` às 14:52:55.

O piso do orçamento agora é **derivado**, não escolhido: quantas leituras cabem
na janela cheia (`COMMAND_WINDOW_CEILING_SECONDS`, 180s) com o menor degrau da
escada, mais uma. Hoje dá 31. Elevá-lo **não cria requisição nenhuma** — quem
marca o ritmo é a cadência; o teto só trunca.

`COMMAND_MAX_POLLS_CEILING` subiu de 12 para 64 para acomodar o piso derivado, e
o `gateway_manager` normaliza a opção no mesmo intervalo — se os dois
discordarem, o piso do motor nunca chega a valer.

## Contratos

`tests/test_command_budget_window_1_12_75.py` afirma a garantia, nunca o número:
nenhuma leitura que caiba na janela pode encerrar a espera pelo orçamento.
Inclui os dois casos de campo com os números do log, e três controles negativos
— o prazo continua encerrando, o teto de segurança continua existindo, e a
escada **não** cresceu para acompanhar o orçamento (o índice satura).

Três contratos carimbavam `len(escada) >= orçamento`, que deixou de valer de
propósito, e um carimbava duas versões literais. Reescritos para a garantia:
saturação do índice, cobertura da janela pela escada, e publicação em duas fases
derivada do `RELEASE_TARGET`.

## E a confirmação em dobro, que só apareceu depois da 1.12.331

Medido em campo em 12/08/2026, conta `acct_1c8b987d`: **cinco dos seis comandos
confirmaram DUAS vezes com o mesmo `ref_`**, a segunda "após 1 leitura(s) e 0s",
cerca de 45s depois — a cadência do boost da tela.

```
08:13:35  unlock (ref_3cf916b9) confirmado ... após 3 leitura(s) e 11s
08:14:17  unlock (ref_3cf916b9) confirmado ... após 1 leitura(s) e  0s
```

A guarda `_settled_confirmation` da 1.12.74 só valia para o boost **anônimo**,
porque naquele momento o site descartava o `request_id`. A 1.12.331 devolveu o
id — e com isso o caso comum virou o **identificado**, que atravessava a guarda,
caía no `INSERT OR REPLACE` de `_register_confirmation` e reescrevia a linha já
confirmada com `started_at` novo. Ela reconfirmava na leitura seguinte, porque o
estado que procura já tinha sido atingido.

Agora a guarda é chaveada pela **identidade**: havendo `request_id`, procura-se o
veredito daquele id. Com identidade exata isto é seguro — um toque novo no botão
gera um `request_uuid` novo, logo um `confirmation_id` novo, e não é suprimido.

Duas mutações provam o par: voltar a guarda para "só anônimo" reprova o caso
novo; ignorar o id de vez reprova o controle negativo
(`test_an_identified_boost_is_never_suppressed`).
