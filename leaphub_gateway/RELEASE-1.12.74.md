## 1.12.74

Distribuição pré-compilada preservada, com publicação em duas fases.

A confirmação do comando chega antes de o carro desfazer o que foi pedido, e um
comando físico volta a ter uma espera só.

### O que estava acontecendo

Medido em 11/08/2026, no registro deste Gateway, num teste de campo do dono.

**Primeiro sintoma — a confirmação chegava atrasada.** O `unlock` foi despachado
às 13:10:47 e a nuvem respondeu em 3,2 s. A confirmação pela telemetria só saiu
às 13:11:45: **54 s, cinco leituras**. Nesse meio-tempo o carro retrancou
sozinho, como faz em ~30 s. A tela mostrou "destravado" quando o carro já estava
trancado, e segundos depois a leitura seguinte — essa fresca — disse "travado".
A tela nunca esteve errada: estava atrasada.

A escada de cadência era `(12, 20, 35, 45, 60, 90, 120, 120)`. Acumulada, as
leituras caíam em 0, 12, 32, 67, 112, 172, 262 e 382 s: apenas três dentro dos
primeiros 32 s, e os dois últimos degraus fora da janela de 180 s, onde
`_within_command_window` tinha de encurtá-los para existirem.

**Segundo sintoma — cada comando ganhava uma espera gêmea.**

```
13:14:29  unlock (ref_…)           confirmado, 3 leituras, 21s
13:14:37  unlock (sem request_id)  confirmado, 1 leitura,  0s    ← gêmea
13:15:04  lock   (ref_163a7451)    confirmado, 3 leituras, 22s
13:15:34  lock   (sem request_id)  confirmado, 2 leituras,  2s   ← gêmea
```

O Gateway arma a espera **nomeada** sozinho, logo após o despacho, com o
`request_id` do comando. O site repete o boost depois, como sinal de
recuperação. A 1.12.70 tornou o casamento simétrico, mas só entre esperas
**pendentes**: quando o boost repetido chega sem id e a nomeada já confirmou, não
há nada pendente para adotar e nasce uma espera nova. Ela confirma na primeira
leitura — o estado que procura já foi atingido quando ela nasce.

E ela custa. A gêmea do `sunshade_open` das 13:16:11 nasceu às 13:17:21, dois
segundos antes de o dono mandar **fechar** a cortina. Gastou as 8 leituras do
orçamento em 111 s procurando a cortina aberta enquanto ela era fechada, manteve
a conta em cadência de comando o tempo todo, e encerrou "sem confirmação
conclusiva". O `windows_open` das 13:18:16, que dividia a mesma conta, morreu por
orçamento 230 s depois, sem veredito nenhum.

### O que mudou

**A escada de confirmação foi redistribuída, sem gastar mais leituras.** Agora é
`(6, 10, 16, 24, 34, 45, 60, 90)`: acumulada 0, 6, 16, 32, 56, 90, 135 e 195 s.
Quatro leituras nos primeiros 32 s em vez de três — antes do retravamento
automático — e a cauda cabendo na janela em vez de depender de encurtamento. O
orçamento continua sendo 8 leituras: as mesmas, distribuídas onde adiantam.

O valor da primeira releitura é **teto em código**
(`COMMAND_FIRST_POLL_CEILING_SECONDS`), e não padrão novo no `config.yaml`. A
instalação existente guarda o valor antigo da opção `telemetry_command_seconds` e
nunca releria um padrão novo — mesma razão de
`COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS` e de `COMMAND_MAX_POLLS_FLOOR`.

**Um boost anônimo que chega depois do veredito deixa de criar espera nova.**
`_adopt_legacy_confirmation` já se protegia disto desde a 1.12.70; o `boost` não
se protegia, e é por ele que a repetição chega. A guarda é estreita de propósito:

- vale **só** quando o boost chega **sem** `request_id`. Com id, quem decide
  continua sendo o casamento da 1.12.62/1.12.70;
- vale **só** para veredito **positivo**. Uma janela que se esgotou sem concluir
  continua podendo ser rearmada — ali o boost do site é recuperação de verdade, e
  recusá-la deixaria o comando sem veredito, que é o defeito oposto e pior;
- vale **só** dentro da janela que o boost está pedindo. Um veredito antigo do
  mesmo comando não bloqueia um comando novo.

A causa raiz é do site — ele descartava o `request_id` antes de mandar o boost, e
a 1.12.331 devolveu — mas o Gateway não pode depender da versão do site para não
duplicar trabalho.

### O que NÃO mudou

O `Dockerfile`, a matriz de comandos, o schema do add-on, o orçamento de leituras
e o prazo de 180 s da janela. Nenhuma opção nova, nenhuma migração.

### Como conferir depois de instalar

No registro do Gateway, depois de um comando:

- deve aparecer **uma** linha `confirmado pela telemetria`, não duas — a linha
  `(sem request_id)` some;
- o tempo até confirmar cai para a faixa de uma a três leituras. No teste de
  campo os comandos já confirmados em 21–22 s passam a caber em ~6–16 s;
- as linhas `Janela rápida … encerrada … sem confirmação conclusiva` deixam de
  aparecer para comandos que já tinham sido confirmados.
