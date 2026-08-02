## 1.12.70

Distribuição pré-compilada preservada, com publicação em duas fases.

O porta-malas abria e a tela dizia que falhou. Esta release conserta as três
causas medidas nos logs de 02/08/2026 entre 13:42 e 14:04 — e corrige o
diagnóstico que tinha sido escrito para uma delas.

### A janela de confirmação perdia as leituras para o backoff errado

Quando um comando é despachado, a assinatura entra em "modo comando": uma janela
de 180 s com cadência própria, que começa em 12 s. Se a leitura de telemetria
falhasse por transporte dentro dessa janela, o atraso da próxima era escolhido
por `fast_mode` — que é `interactive or command_mode`, ou seja, o mesmo balde de
quem apenas está com a tela aberta. O resultado:

| situação | próxima leitura |
|---|---|
| site aberto | **45 s** |
| site fechado | **120 s** |
| o que a janela pedia | 12 s |

Uma única falha consumia um quarto da janela; duas, quase toda. É o que o log
mostra, com todas as letras:

```
14:03:36  trunk_close despachado (ref_f98740ab)
14:03:38  finalizado, ack=library_returned, resultado_remoto=completed
14:04:10  Read timed out em acct_...; nova leitura em 45 s
   —      o trunk_close nunca aparece confirmado
```

A janela ganha o seu próprio backoff, `(8, 15, 25, 40, 60, 90)`: a primeira
retentativa cabe na cadência que a janela publica, e três falhas seguidas ainda
somam menos que os 180 s. E **nenhum** reagendamento por falha pode cair depois
do fim da janela: uma leitura que chega com a espera já encerrada por prazo não
confirma nada, só custa uma chamada à nuvem. Os três caminhos de falha do ciclo
passam a encurtar o atraso para caber no que resta, com piso de 2 s para o
encurtamento não virar laço apertado.

Fora do modo comando nada muda: a telemetria de fundo conserva o backoff longo,
que é o que protege a conta Leapmotor.

### O tempo limite era da telemetria, e quem sofria era o comando

O cliente Leapmotor da sessão persistente é o **mesmo** que despacha os
comandos — a sessão é emprestada de propósito, para não abrir um segundo login
logo depois de a ação ser aceita. Só que ele nascia com
`telemetry_request_timeout_seconds`, cujo padrão é **15 s**.

O despacho mais lento medido, `sunshade_position`, levou **12,686 s**. Folga de
2,3 s: com a nuvem ~18% mais lenta, aquele comando estoura o limite e falha.
A leitura de status, que é a operação para a qual os 15 s foram escolhidos,
raramente passa de 3 s.

O tempo limite é do cliente, não da chamada, então ele tem de servir ao
consumidor mais exigente dos dois. Passa a valer um piso de **25 s** — piso, não
valor: quem configurou mais continua com o que configurou. E é piso **no código**
de propósito: instalações existentes guardam o valor antigo nas opções do add-on
e nunca releriam um padrão novo do `config.yaml`. Um padrão novo seria uma
correção inerte, e este projeto já pagou por uma.

### Um comando físico, duas esperas — e a gêmea confirmava sozinha

O casamento entre um boost e uma espera pendente era assimétrico:

- boost **sem** `request_id` adotava a espera existente;
- boost **com** `request_id` nunca adotava uma espera sem id — criava a sua.

Quem arma a espera nem sempre conhece o id (o arme interno, um site mais antigo).
Então o mesmo comando físico terminava com **duas** esperas pendentes: uma
identificada e uma anônima. A anônima confirma na primeira leitura, porque o
estado dela já está satisfeito quando ela nasce, e escreve no log

```
Comando sunshade_close (sem request_id) confirmado ... 1 comando(s) ainda aguardam
```

que se lê exatamente como se o comando recém-despachado tivesse sido o
confirmado. Duas vezes em campo, com o mesmo desenho:

| hora | evento |
|---|---|
| 13:42:45 | `sunshade_open (ref_0cb26cc9)` confirmado → **0 aguardam** |
| 13:43:16 | `trunk_open` despachado |
| 13:43:23 | `sunshade_open` **(sem request_id)** confirmado → **1 aguarda** |
| 14:03:08 | `sunshade_close (ref_f37a84ee)` confirmado → **0 aguardam** |
| 14:03:36 | `trunk_close` despachado |
| 14:03:43 | `sunshade_close` **(sem request_id)** confirmado → **1 aguarda** |

O casamento passa a ser simétrico: id novo sobre espera anônima da mesma dupla
comando+veículo **adota e batiza** a espera, em vez de duplicá-la. Id
**diferente** continua sendo outro comando e continua merecendo a sua própria
espera — sem isso a 1.12.62 seria desfeita.

A segunda fonte de gêmeas era a adoção da janela legada. As colunas de comando
da assinatura sobrevivem ao veredito quando outra espera ainda estava pendente
no ciclo que as leu; o ciclo seguinte relia as mesmas colunas e ressuscitava um
comando **já confirmado** como espera nova. Sem `request_id` no contexto — que é
como ela aparece no log —, ela ganha um `confirmation_id` próprio e escapa da
chave primária que deveria bloqueá-la. Passa a haver guarda: um comando que já
recebeu veredito depois do próprio despacho nunca é readotado.

### O que NÃO foi feito, e por quê

A decisão registrada em 02/08 era **"forçar refresh/wakeUp antes de amostrar"**.
Ela não entrou, e não deve entrar: **a leapmotor-api 0.3.2 — a versão fixada em
`requirements.txt` — não expõe nenhuma primitiva de despertar.** Medido método a
método no cliente instalado: existe uma única leitura de estado
(`vehicle/v1/status/get`, que devolve o último instantâneo que o carro subiu) e
nenhuma operação de acordar ou de forçar atualização. `try_wake_vehicle`, que
procura seis nomes por reflexão, devolve `attempted: False` em toda instalação
atual.

Escrever a chamada assim mesmo seria código que não faz nada — e a medição
mostra que ela não era necessária: as leituras não estavam lentas porque o carro
dormia, e sim porque uma falha de transporte mandava a próxima para 45 s ou
120 s. Quem acorda o carro é o próprio comando; foi o que aconteceu às 13:42:23,
logo depois da cortina.

A medição fica registrada no `try_wake_vehicle`, e um contrato falha se ela sair
do código — ou se a biblioteca ganhar a primitiva, porque aí a decisão volta a
ser implementável.

### O contrato

`test_command_window_backoff_1_12_70` tem 10 verificações, e todas exercitam a
derivação em vez de citar a linha que hoje a implementa:

- o backoff da janela é estritamente menor que o da presença e que o de fundo,
  a primeira retentativa cabe na cadência publicada, e três falhas ainda somam
  menos que a janela;
- o encurtamento respeita o prazo, tem piso, e **não** age fora do modo comando;
- boost identificado adota e batiza a espera anônima, com o controle negativo de
  que id diferente continua criando espera própria;
- boost anônimo continua adotando a identificada — o que a 1.12.62 comprou;
- comando já resolvido não é ressuscitado, com o controle de que um comando de
  verdade em voo continua sendo adotado e de que um veredito **anterior** ao
  despacho atual não bloqueia nada;
- o piso do tempo limite dá folga real sobre o despacho medido, cabe no teto que
  o `create_client` aceita e não encurta o que o operador configurou;
- a biblioteca não tem primitiva de despertar, verificado contra um dublê.

`dentes_70.py` remove cada garantia do código e exige que o contrato reprove:
**13 mutações, 13 detectadas.** Duas passaram na primeira rodada, e as duas
ensinam:

1. A asserção `"command_mode=command_mode" in corpo` passava **por acidente** —
   essa string já existia no mesmo corpo, nas chamadas a
   `_manual_operation_blocks`. Trocada por uma que olha a chamada certa.
2. O teste da ressurreição usava um `request_id` que colidia com a chave
   primária da linha já resolvida, e por isso o `INSERT OR IGNORE` não criava
   fantasma nenhum — o teste passava com a garantia removida. O fantasma real
   nasce **sem id**; é a ausência dele que lhe dá `confirmation_id` próprio.

### Um contrato reescrito por vício, não por defeito

`test_release_publication_gate_1_12_41` carimbava `assert target == "1.12.69"` e,
por construção, reprovaria esta release e todas as seguintes. **Nona ocorrência
do mesmo vício no projeto.** Ele passa a afirmar o que existe para comprar: que
o `RELEASE_TARGET` tem forma de versão, que os seis módulos anunciam exatamente
ele, que o `config.yaml` só pode estar **atrás** — nunca à frente, que é o estado
em que o Home Assistant ofereceria uma imagem que o GHCR ainda não tem — e que as
notas do alvo existem nos dois lugares em que a recuperação manual as procura.
Com isso ele também passa a pegar sozinho o bump incompleto que custou cinco
arquivos na 1.12.52.

### Sem efeito colateral

- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- Nenhuma mudança na matriz de comandos nem em `COMMAND_CONFIRMATION_FIELDS`.
- Nenhuma mudança na cadência da janela de confirmação em caminho de sucesso:
  `(12, 20, 35, 45, 60, 90, 120, 120)` continua igual. O que muda é o caminho de
  **falha**, que antes ignorava a janela.
- `Dockerfile` intocado.
- `config.yaml` intocado: o CI o promove depois de a imagem ficar pública.

### Como medir em campo

Repetir a sequência com o carro dormindo e com o carro em `parked`, e comparar,
por comando: `handle_command`, número de leituras, tempo até confirmar, e se
alguma entrada `(sem request_id)` aparece. A linha de confirmação passa a trazer
o tempo até confirmar direto no log — era o número que a análise anterior teve de
reconstruir somando carimbos de hora de linhas diferentes.
