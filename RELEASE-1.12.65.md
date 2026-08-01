## 1.12.65

Distribuição pré-compilada preservada, com publicação em duas fases.

### Carro acordado é lido rápido; só o que dorme cai para lento

Relato do proprietário em 01/08/2026: *"agora nesse instante o porta-malas está
aberto porém ali não mostra"*. Medido no site no mesmo minuto: `captured_at`
travado 12 minutos atrás, `trunk_open: false`, e a leitura anterior ainda
descrevendo quatro portas abertas.

A 1.12.64 tinha consertado o desenho — ele deixou de ficar atrás da telemetria.
O que sobrou é anterior a isso: **a telemetria em si não chegava**.

A causa está em `_adaptive_interval()`. Parado devolve `parked_seconds` (90s)
apenas nas seis primeiras leituras; da sexta em diante devolve `sleep_seconds`
(600s). Seis vezes noventa são nove minutos — ou seja, o critério de "dormindo"
era o **relógio**, e nunca o carro. Um veículo na garagem há mais de nove
minutos já estava na cadência de sono, e o porta-malas aberto depois disso
esperava a próxima leitura lenta para aparecer.

Foi por isso que só um comando parecia "acordar" a tela: o modo de confirmação
tem cadência própria e curta, e passava por cima do rebaixamento.

Agora a atividade observada decide. `activity_fingerprint()` resume o que muda
quando alguém mexe no carro — portas, porta-malas, capô, vidros, cortina,
trava e cabo — e `parked_streak_after_activity()` recomeça a contagem quando
essa assinatura muda. Um carro em que alguém mexeu está acordado por definição,
e volta à cadência de 90s.

### Custo

Nenhum aumento para carro parado de verdade. Bateria, autonomia e temperatura
oscilam com o veículo dormindo e **ficam de fora da assinatura** de propósito:
incluí-las faria a impressão digital mudar a cada leitura e a cadência rápida
valer para sempre, que é o oposto do pedido. Há teste dedicado para isso.

Depois de uma atividade, o carro tem no máximo seis leituras rápidas (nove
minutos) antes de voltar a dormir, exatamente como antes.

### Sem efeito colateral

- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- A prioridade do comando manual e a janela de confirmação seguem intocadas.
- O registro de atividade é por assinatura e fica em memória: reiniciar o App
  custa um ciclo rápido a mais, nunca um ciclo lento a mais.
- `Dockerfile` intocado. Distribuição continua pré-compilada via GHCR, com
  promoção somente após validação pública da imagem.
