# Leap Hub Gateway 1.12.62 — o comando esquecido

A 1.12.61 fez a confirmação voltar a rodar. Esta conserta o que acontece quando
há **mais de um** comando esperando: o anterior era esquecido sem veredito.

## O caso, medido em produção

30/07/2026, mesma assinatura, mesmo carro:

| horário | evento |
|---|---|
| 13:34:40 | `sunshade_open` enviado, janela de confirmação armada |
| 13:36:03 | `unlock` enviado |
| 13:37:38 | janela fecha, log relata **só** `unlock` |

Nenhuma linha sobre o `sunshade_open`, em lugar nenhum. Nem confirmado, nem
inconclusivo: esquecido. E o botão da cortina, do lado do site, continuou
girando — porque o veredito que ele espera nunca foi emitido.

## A causa

A janela de confirmação morava em colunas únicas da linha da assinatura:

```
command_key, command_vehicle_id, command_context_json, command_started_at
```

Em `boost()`, `same_command_window` exige mesma chave, mesmo veículo e mesmo
`request_id`. Um segundo comando com chave diferente não é a mesma janela, cai no
`UPDATE` que **sobrescreve** essas colunas e zera `command_poll_count`. A partir
daí só existe o segundo comando. O primeiro perdeu o contexto que o matcher
usaria para julgá-lo, e ninguém mais o procura.

Uma assinatura, uma janela. Dois comandos não cabiam.

## A correção

**Uma linha por comando, não por assinatura.** Tabela nova e aditiva,
`command_confirmations`, com uma espera por `request_id`: hora de partida,
contexto, prazo e contagem de leituras próprios. Cada leitura de telemetria é
confrontada com **todas** as esperas pendentes, e cada uma recebe o seu veredito.

- Repetir o boost do mesmo comando continua reaproveitando a espera — o site
  repete como sinal de recuperação, e criar outra reiniciaria a contagem a cada
  repetição.
- A leitura passa a cobrir o veículo-alvo de todas as esperas. Restringir ao
  veículo do último comando cegava as demais.
- `command_until` da assinatura cresce, nunca encolhe: um comando novo e curto
  não pode encurtar a janela de um comando anterior mais longo.
- Uma janela em voo no momento da atualização é **adotada** da linha antiga, com
  a hora de partida original — senão o comando que estava esperando morreria
  justamente na versão feita para não perder veredito.
- Espera abandonada (assinatura liberada, credencial exigida) é encerrada por
  prazo, e não sobrevive consumindo ciclos.

## O segundo defeito, no mesmo caminho

`command_max_polls` era 5, e a cadência é `12, 20, 35, 45, 60, 90, 120, 120`.
Cinco leituras esgotam a janela em ~112s — mas `command_until` dá 180s. O
`unlock` daquele mesmo dia teve uma amostra a **+89s** e ainda assim foi
declarado inconclusivo, com quase um minuto de janela por usar. Carro acordando
não cabia no orçamento.

Agora quem encerra a espera é o **prazo**; a contagem de leituras virou teto de
segurança, com piso 8 — o que cobre os 180s inteiros com a cadência atual. O piso
e o teto ficam em `COMMAND_MAX_POLLS_FLOOR`/`CEILING`, lidos pelo
`gateway_manager` e pelos contratos, porque o número estava repetido em três
lugares e um contrato reprovava por carimbar o antigo.

## Diagnóstico

`/status` passa a informar `pending_confirmations`, com uma linha por espera
(comando, `request_id`, leituras já gastas, tempo restante) e as últimas
resolvidas. Com a janela única não havia como o painel mostrar que um segundo
comando havia substituído o primeiro.

O log de confirmação passou a ser por comando: cada espera diz o seu nome, o seu
`request_id`, quantas leituras consumiu e se fechou por prazo ou por orçamento.

## Sem alteração

- Matriz de comandos, `COMMAND_CONFIRMATION_FIELDS` e a regra de frescura seguem
  idênticos. A margem de 2s não mudou.
- Nenhuma mudança em credenciais, OCPP, MQTT ou dados existentes. A tabela nova é
  aditiva e criada com `CREATE TABLE IF NOT EXISTS`; nenhuma coluna foi removida,
  e as antigas continuam preenchidas para o painel.
- `Dockerfile` intocado. Distribuição continua pré-compilada via GHCR, com
  promoção somente após validação pública da imagem.

## O que esta release não resolve

O botão da cortina do teto **continua** sem concluir sozinho, e agora se sabe por
quê: neste C10 a nuvem publica o estado da cortina na chave que o connector mapeia
como teto solar, então `sunshade_open` fica sempre nulo e o matcher não tem o que
ler. Confirmado em campo: abrir a cortina acende o selo TETO na figura do carro.
A partir desta versão, ao menos, esse comando recebe um veredito honesto de
inconclusivo em vez de silêncio. O mapeamento se fecha com as chaves cruas, que o
site 1.12.265 passou a exibir no diagnóstico técnico.
