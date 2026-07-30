# Leap Hub Gateway 1.12.59 — o resto da superfície, sob liberação por proprietário

A 1.12.58 fechou a paridade do que era seguro anunciar para todo mundo. Sobraram nove
comandos que eu tinha deixado de fora, cada um por um motivo: dois movem o carro, três
instalam firmware, dois têm pacote sem vocabulário documentado, um é só de outro modelo
e um não tem descrição funcional.

Esta versão inclui todos, atrás do mesmo portão do Sentinela: **o administrador libera o
recurso para um proprietário específico, e quem aciona confirma explicitamente**. O
motivo de cada um não estar na matriz estável não desapareceu — ele passou a ser a razão
de estar no gate.

## Os nove

| comando | cmd | direito | parâmetros |
|---|---|---|---|
| `autopark` | 150 | 150 | — |
| `piloted_parking` | 350 | 350 | pacote conferido por forma |
| `seat_adjust` | 280 | 280 | pacote conferido por forma |
| `rear_seats` | 470 | 470 | `seat_info` |
| `on3_on` / `on3_off` | 410 | 410 | — |
| `fota_download` | 390 | 390 | `task_id` |
| `fota_install` | 391 | 391 | `task_id` |
| `fota_schedule` | 392 | 392 | `task_id`, `schedule_time` |

Todos declaram o direito que exigem, então seguem o filtro de capacidade: só aparecem
para o carro que tem o direito, com o fail-open preservado quando a nuvem não informa
capacidade.

**Correção de uma afirmação minha da 1.12.58:** eu havia registrado que o `on3` não tinha
código de direito. Tem — `VehicleRight.ON3 = 410`. A tabela `REMOTE_ACTION_SPECS` da
biblioteca associa cada ação ao direito exigido, e é dela que saíram todos os códigos
acima, em vez de suposição. O que o `on3` continua não tendo é descrição do que o modo
faz; a biblioteca só diz "domestic models".

## Três travas, em série

1. **Liberação do administrador**, por proprietário e por recurso — no site, pelo mesmo
   mecanismo do Sentinela (`ExperimentalFeatureAccessService`).
2. **Confirmação experimental** de quem aciona (`experimental_confirmed`), já existente.
3. **Reconhecimento de movimento** (`motion_acknowledged`), novo, só para `autopark` e
   `piloted_parking`.

A terceira precisa de explicação. As duas primeiras dizem que o recurso está aberto para
aquela conta; nenhuma delas diz nada sobre *agora*. Um comando que faz o carro se mover
sozinho não deveria depender de um único toque numa tela de celular que pode estar no
bolso, a quilômetros do carro. O gateway não tem como verificar presença nem campo de
visão — mas pode exigir que isso seja declarado no momento do envio, e registrar que foi.
É uma trava contra distração, não contra má-fé, e é o máximo que este lado da pilha
consegue oferecer honestamente.

Se preferir sem essa trava, é um conjunto de uma linha (`VEHICLE_MOTION_COMMANDS`) —
mas ela está aqui de propósito.

## Pacote cru: conferir a forma quando não há vocabulário

`seat_adjust` e `piloted_parking` são declarados na biblioteca assim:

> The ``cmd_content`` is the full JSON payload string.

Não há lista de campos. Diferente do `prepare_car`, que tem um agendamento equivalente
(361) de onde aprender a estrutura, aqui não há nada de onde inferir — e inventar campos
seria pior que não validar, porque daria aparência de conferência.

A saída foi conferir o que dá para conferir sem inventar semântica. `raw_command_payload()`
exige objeto, no máximo **12 chaves** com nome plausível (`^[A-Za-z][A-Za-z0-9_]{0,39}$`),
valores escalares ou **um único nível** de objeto com até **8 subcampos**, texto de até
**120 caracteres**, inteiros numa faixa sã, e **512 bytes** no total serializado. Lista,
`None`, aninhamento fundo e chave com espaço ou pontuação são recusados.

Isso deliberadamente **não** garante que o comando funcione — garante que o gateway não
seja um túnel para conteúdo arbitrário até a nuvem do fabricante. É a razão de estes dois
exigirem liberação por proprietário, e não a liberação que torna o pacote seguro.

## FOTA

`task_id` identifica a tarefa de atualização na nuvem e é obrigatório. O gateway ainda
não expõe a listagem de tarefas, então por ora o número é informado por quem aciona — e
conferir aqui (ausente, zero, negativo, não numérico) evita descobrir o erro como uma
recusa opaca da nuvem. Expor a listagem é o próximo passo natural, e está anotado.

O agendamento exige `AAAA-MM-DD HH:MM:SS` **e** uma data que exista: `2026-13-01` e
`2026-02-30` casam com o formato e são recusadas pela conferência de calendário.

## Contratos

`tests/test_experimental_surface_1_12_59.py` cobre: nenhum dos nove na matriz estável, o
direito de cada um, confirmação experimental obrigatória para todos (sem que nada de rede
aconteça), o interlock de movimento exigido nos dois que movem o carro e **não** exigido
nos outros, o validador de forma aceitando objeto raso, texto JSON e um nível de
aninhamento e recusando quinze formas de conteúdo malformado, `seat_info` recusando texto
inesperado, e FOTA recusando `task_id` e data inválidos.

Uma nota sobre o próprio teste: a checagem de que os comandos *não* de movimento
dispensam o interlock foi escrita afirmando o conjunto, e não chamando `handle_command`.
Com a confirmação experimental presente eles seguem adiante e chegam a abrir sessão — num
ambiente com a biblioteca instalada, como o CI, isso sairia para a rede durante o teste.

Os contratos da 1.12.57 e da 1.12.58 não precisaram de uma linha alterada neste bump:
ambos afirmam `versão >= X`, não igualdade. Os outros 43 arquivos mudaram só por fixarem
versão exata.

## Sem alteração

Nada em credenciais, OCPP, MQTT, schema, migrations ou dados existentes. Nenhum dos
comandos novos entra no `COMMAND_CONFIRMATION_FIELDS` — declarar um mapeamento adivinhado
de telemetria produziria confirmação falsa. Eles valem pelo aceite do envio.

`Dockerfile` intocado.

## O que falta do outro lado

O gateway aceita os nove, mas **o site ainda não os oferece**. Falta lá: as chaves de
recurso por grupo no `ExperimentalFeatureAccessService` (para o administrador poder
liberar ajuste de assento sem liberar movimento do carro), o formulário do administrador
iterando as definições em vez de ter um checkbox fixo do Sentinela, e os controles no
painel do veículo. Enquanto isso não for feito, estes comandos existem no gateway e não
têm como ser acionados.

Atenção para um detalhe do mecanismo atual: `ExperimentalFeatureAccessService::canManage()`
e `isEnabled()` exigem `environment === 'staging'`. Seguindo o modelo do Sentinela à
risca, estes recursos aparecem **somente em staging** — em produção ficam invisíveis
mesmo liberados.
