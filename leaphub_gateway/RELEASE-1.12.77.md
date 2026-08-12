# Leap Hub Gateway 1.12.77

## Com a tela aberta, a cadência acompanha o degrau do comando

`interactive_seconds` valia **20s** (piso 15s) e governa TODOS os estados
enquanto há presença — ver o ramo `if interactive:` de `_adaptive_interval`.
Ninguém tinha questionado esse número.

Medido em campo em 12/08/2026 (conta `acct_1c8b987d`), o carro publica uma
mudança de trava em **~0-12s**:

```
lock  confirmado após 1 leitura(s) e  0s
lock  confirmado após 1 leitura(s) e  1s
lock  confirmado após 3 leitura(s) e 12s
```

Com leitura a cada 20s, boa parte da espera que o dono sente é **nossa**, não do
carro: o dado já está na nuvem e a gente ainda não perguntou.

## O número errado que quase me enganou

Eu tinha descartado esta mudança usando os tempos da **cortina** (29-44s),
concluindo que o carro era lento demais para valer a pena. O dono corrigiu: a
cortina leva **30-40s no próprio mecanismo**. Aquilo nunca foi latência de
telemetria — era o motor girando. Tirando a cortina da amostra, a publicação
cai para 0-12s e a conta inverte.

Fica registrado porque o erro é reincidente: **tempo de mecanismo não é latência
de sistema**, e misturar os dois faz descartar o conserto certo com dado certo.

## Por que 6s, e não 3s ou 1s

6s é o primeiro degrau da escada de confirmação de comando
(`COMMAND_FIRST_POLL_CEILING_SECONDS`), que **já roda em produção sem disparar
rate-limit**. É um valor provado, não escolhido.

O piso é 5s por medição, não por gosto: o round-trip HTTPS ficou entre **2,1s e
4,5s** em 12/08. Abaixo disso as chamadas empilham sem trazer dado novo, porque
`vehicle/v1/status/get` devolve o último snapshot que o **carro** subiu — não uma
leitura ao vivo. Perguntar mais rápido que o carro publica não cria informação.

E o castigo de errar para baixo é desproporcional: o rate-limit custa
`rate_limit_cooldown_seconds = 900`. Trocar 20s de atraso por 900s de cegueira
seria péssimo negócio.

## Teto em código, não padrão no config.yaml

A instalação de campo tem `telemetry_interactive_seconds: 20` **gravado**, e uma
opção armazenada nunca relê um padrão novo. Mudar só o default não mudaria nada
no carro do dono. Mesma razão de `COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS` e
`COMMAND_MAX_POLLS_FLOOR`.

## A telemetria de FUNDO não mudou

Só a presença muda de ritmo. Acelerar o fundo multiplicaria chamadas o dia
inteiro — que é justamente o que o rate-limit pune. O contrato tem controle
negativo para isso.

## Comentário defeituoso removido

O comentário de `COMMAND_FIRST_POLL_CEILING_SECONDS` ainda afirmava "o orçamento
total de leituras não muda: são as mesmas 8, apenas distribuídas mais cedo".
Essa frase **era** o defeito da 1.12.74, e a 1.12.75 provou que era falsa ao
derivar o piso do orçamento — mas o comentário ficou para trás, contradizendo o
código logo abaixo dele. Um comentário que afirma o que o código refuta é
armadilha para o próximo leitor.

## Prova

`tests/test_interactive_cadence_1_12_77.py` afirma a garantia, nunca o literal:
com a opção **gravada** de 20s, a cadência interativa não pode ser mais lenta que
o primeiro degrau do comando. Sob a 1.12.76 ele reprova com os números exatos
(20s contra 6s). Três controles negativos: o fundo não acelerou, o piso impede
cair abaixo do round-trip, e o teto realmente trunca um valor gravado alto.
