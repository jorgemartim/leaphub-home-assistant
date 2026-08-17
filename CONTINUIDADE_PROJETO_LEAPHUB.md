# CONTINUIDADE DO PROJETO LEAP HUB

> Regra principal: continuar do estado atual; não recomeçar arquitetura, não
> alterar comportamento homologado sem evidência de campo e atualizar este
> arquivo ao final de cada rodada.

## Repositório e publicação

- Repositório: `jorgemartim/leaphub-home-assistant`.
- Fluxo: commit funcional staged → GitHub Actions validate/build/smoke/GHCR →
  commit automático `[gateway-published]`.
- Produção/Site ficam intocados até aprovação explícita.
- Uma única sessão/cliente Leapmotor por conta; sem wake inventado e sem segundo
  cliente concorrente.

## Linha homologada recente

- 1.12.87: restauração do runtime funcional 1.12.84.
- 1.12.88: status cooperativo one-shot.
- 1.12.89: bounded cloud reads, teto de 4 s.
- 1.12.90: confirmação de clima por modo físico AUTO/COOL/HEAT.
- 1.12.91: precheck de comando sem lock global.
- 1.12.92: retorno pós-dispatch sem bookkeeping redundante.
- 1.12.93: arme de confirmação SQLite fora do caminho crítico, FIFO local.
- 1.12.94: telemetria persistida antes do render; imagem em worker local sem
  cliente/token/credenciais/rede.

## Campo 1.12.94 — 14/08/2026

- Controles permaneceram rápidos: `climate_on` ~625 ms, `quick_heat` ~612 ms,
  `quick_cool` ~635 ms, `trunk_open` ~624 ms e `trunk_close` ~638 ms.
- `climate_off` ~2,525 s, exatamente 2 tentativas e `repetição_segura=True`.
- Telemetria após aquecimento: coleta completa chegou a ~914 ms; outras leituras
  ficaram aproximadamente entre 2,7 e 4,0 s.
- O antigo `serialize_vehicle` de 40–44 s desapareceu.
- Render visual ficou isolado, mas ainda mediu ~7–11 s por imagem.
- Como havia um único worker visual, imagens de contas diferentes podiam formar
  fila mesmo sem bloquear comandos/telemetria.

## Gateway 1.12.95 — objetivo da rodada

- Base publicada obrigatória: 1.12.94
  (`b96097d2c05d68a6079729ce194309dd3405acc4`).
- Controles: congelados; somente regressão automática.
- Polling/timeouts: congelados nesta versão.
- Imagem: lazy decode das camadas do ZIP, WebP lossless com `method=0`, contrato
  visual 16, dois workers exclusivamente locais e métricas de
  pacote/render/base64/total.
- A imagem continua incapaz de abrir rede ou receber cliente Leapmotor.
- Próxima validação de campo: medir separadamente controle, coleta de telemetria
  e logs `Imagem local ... pacote=... render=... total=...`.

## Guardrails obrigatórios

- ACK-first.
- C10 `climate_off` usa `operate=off`.
- Máximo de 2 transmissões seguras para `climate_off`; nunca terceira.
- Porta-malas e cortina sem retry físico automático.
- Supersessão de confirmações antigas.
- Resultado de comando anunciado imediatamente ao Site.
- Telemetria, comando e imagem não podem manter as travas uns dos outros.
- Site/PWA não são alterados nesta rodada.

## Gateway 1.12.96 — implementação staged

- Base: 1.12.95 publicada (`672d4dcca0f6928d21f8eb6141bf815fb9bdb5e8`).
- Controles físicos, ACK-first, payloads C10, imagem, HMAC e OCPP continuam congelados.
- Confirmação: poll inicial imediato preservado; override exclusivo de command-mode usa 5s → 5s → 8s, mantendo a cadência estrutural/interativa de 6s intacta.
- Official: rota read-only existente usa somente sessão persistente pronta e autorizada; descoberta SQLite bounded, ordem conta → vaga global de baixa prioridade → sessão e chamada única sem retry/login/refresh próprio.
- `begintime/endtime` são assinados e enviados em milissegundos.
- Escopo do veículo é revalidado por `vehicle_ids_json`; resposta é somente shape redigido e nenhum `official_*` é promovido antes do teste real do C10.
- `config.yaml` fica 1.12.95 no commit funcional; promoção para 1.12.96 continua exclusiva da automação após GHCR público.
- Próximo campo: publicar 1.12.96, instalar no HA, medir confirmação e coletar evidência redigida do drivingRecord; só depois preparar Site Beta 1.12.360.


## Hotfix Gateway 1.12.97 — runtime Official

- Base: 1.12.96 publicada (`215c4215d58ce3e2439c1bb2dcec0041995414c4`).
- Homologação física 1.12.96: comandos, telemetria, imagem e isolamento sem regressão detectada.
- Falha nova isolada à sonda Official: primeira chamada real retornou HTTP 500 em ~0,12s.
- Traceback: `ModuleNotFoundError: No module named 'official_trip_probe'` ao entrar em `execute_driving_record_probe`; nenhuma chamada Official chegou à Leapmotor.
- Causa: Dockerfile copiava `official_trip_probe.py` para `/app`, mas não o instalava com nome interno em `site-packages`, ao contrário dos demais módulos runtime.
- 1.12.97: instalar como `leaphub_official_trip_probe.py`, importar esse nome primeiro e manter fallback local.
- Congelados: ACK-first, payloads C10, climate_off máx. 2 transmissões, sem retry trunk/sunshade, cadência pós-comando 5/5/8, estrutural/interativa 6s, telemetria, imagem 1.12.95, HMAC, OCPP e Produção.
- Próximo passo: publicar 1.12.97, instalar somente após Actions + `[gateway-published]`, repetir UMA sonda read-only e analisar apenas shape redigido.


### Pré-validação integral da 1.12.97 — contratos históricos

- O primeiro teste de campo da 1.12.96 encontrou `ModuleNotFoundError: official_trip_probe` antes de qualquer chamada Official à Leapmotor.
- A 1.12.97 permanece um hotfix de empacotamento/import; nenhuma lógica de controle físico foi reaberta.
- Falhas anteriores dos publishers 1.12.97 ocorreram antes de commit/push: quoting do WSL, leitura de caminho do Git, `wslpath` de `%TEMP%` e CRLF no stdin.
- A pré-validação final inclui scanner dos contratos históricos, artefatos root/add-on/recovery do alvo, smoke isolado de `site-packages`, regressões direcionadas e validator oficial completo repetido três vezes.
- `config.yaml` permanece 1.12.96 até a promoção automática após imagem GHCR pública.


## 2026-08-15 — Gateway 1.12.98 preparado após homologação 1.12.97

- Gateway 1.12.97 homologado em campo, inclusive uma única sonda Official `drivingRecord` real no C10: HTTP 200, sessão reutilizada, ~1,19 s, sem retry e sem corpo bruto.
- Shape comprovado: totais cumulativos + `detail` diário; não há evidência de viagens individuais nesse endpoint.
- 1.12.98 limita o Official a allowlist dos campos observados e conserva `unit_status=unverified`; o Site não converte RAW para km/kWh.
- `sunshade_position` já enviava corretamente 0-100 convertido para degraus nativos 0-10, porém ficava fora de `TELEMETRY_CONFIRMABLE_COMMANDS`; logs de campo mostraram `confirmation_pending` sem FAST interno.
- Telemetria do C10 comprova `sunshade_percent` em movimento (ex.: 48% → 100%). A 1.12.98 usa esse campo somente para confirmação, sem mudar o despacho físico e sem retry.
- `sunshade_open/close`, clima, trunk, janelas, 5/5/8, imagem, OCPP e HMAC permanecem congelados.
- Site Beta 1.12.360 é o par compatível: Official / Snapshots / Calculado separados, ABRP preserva `captured_at`, catch-up visual sem F5. Produção continua intocada.


## 2026-08-15 — Gateway 1.12.99 diagnóstico de campo da cortina

- Gateway 1.12.98 e Site Beta 1.12.360 instalados com Health saudável.
- Official diário já retornou 8 dias RAW separados de Snapshots/Calculado.
- Em campo, `sunshade_position` apresentou comportamento não linear/inconsistente:
  0% fechou fisicamente; em tentativas distintas 100% foi associado a abertura
  parcial (~15%) e 50% a abertura total, mas os resultados não foram reproduzíveis.
- Logs também tiveram `result_timeout`, refresh cooperativo, timeouts de leitura e
  confirmações supersedidas; portanto não é seguro atribuir cada movimento ao
  último clique sem correlação explícita.
- Houve confirmações reais de `sunshade_position` pela telemetria (ex.: 22:56:01,
  23:09:59 e 23:12:04), provando que a janela FAST funciona, mas a 1.12.98 não
  registrava o percentual solicitado nem cada valor observado.
- Hipótese a testar: repetir o mesmo valor enquanto o motor se move pode agir como
  pausa/stop. Ainda não comprovada.
- A 1.12.99 NÃO muda a transmissão. Apenas registra `pedido_site`, `valor_nativo`,
  `esperado_telemetria`, `observado` e `match` para cada intenção/amostra.
- Uma transmissão por intenção, sem retry físico novo. Produção continua intocada.


## Gateway 1.12.100 — janelas C10/B10 + confirmação final

Base limpa: `121e73229072c28ca0238d9738a8505c62544753` (1.12.99 publicada).

- UI/telemetria continuam 0-100%;
- C10/B10 escrevem cmd 230 em 0-10;
- abrir=10, fechar=0;
- T03/modelos desconhecidos continuam 0-100;
- `windows_position` entra na FAST e na supersessão windows;
- abrir/fechar exige as quatro janelas;
- resultado FAST final é anunciado ao site;
- nenhum retry físico de janela foi criado;
- cortina e OCPP permanecem inalterados.

A REV3 usa worktree limpo, então as tentativas parciais anteriores não participam da publicação.

### REV4 — alinhamento do Dockerfile e baseline Windows

Na REV3:
- 31 testes direcionados passaram;
- a suíte ampla teve 469 passes e 2 falhas;
- uma falha era real desta candidata: a asserção do `official_trip_probe` no
  Dockerfile ainda estava em 1.12.99;
- a outra era `test_ocpp_sqlite_single_writer_1_12_45.py`, falha histórica
  somente no Windows e já documentada no histórico do projeto.

REV4 alinha o Dockerfile a 1.12.100, não altera OCPP e executa novamente os
contratos direcionados e a suíte ampla Windows, excluindo apenas os três
contratos históricos Windows-only. A CI Ubuntu executa tudo sem exclusões antes
de qualquer promoção.


## Gateway 1.12.101 - diagnostico das quatro janelas

Com quatro janelas fisicamente abertas, o Leap Hub mostrou `2 aberta(s)` e somente duas tags. O pacote oficial possui `carpic_leftbehind_window_close.png`; a logica visual traseira fica protegida por teste.

A lacuna restante e a telemetria traseira. A 1.12.101 adiciona `WINDOW_TELEMETRY_DIAG`, sanitizado e limitado, para identificar os sinais traseiros reais no `status.raw` sem registrar dados sensiveis nem alterar comandos fisicos.


### 1.12.101 REV2 — teste de versão future-proof

A primeira execução da 1.12.101 passou 33 testes direcionados e falhou somente
porque `test_command_confirmation_announce_1_12_100.py` exigia literalmente
`gateway_version == "1.12.100"`. O runtime 1.12.101 retornou corretamente
`1.12.101`.

O teste foi corrigido para comparar `gateway_version` com
`telemetry.ENGINE_VERSION`, preservando o contrato sem congelar futuras versões.
Nenhuma alteração adicional foi feita no dispatch, retry, janelas, cortina ou OCPP.

### 1.12.101 REV3 — CHANGELOG de alvo único

A REV2 passou 34/34 testes direcionados, mas a suíte ampla parou no contrato
`single_changelog_heading`. O repositório exige que `leaphub_gateway/CHANGELOG.md`
contenha somente um cabeçalho de versão e que ele seja exatamente o `RELEASE_TARGET`.

A candidata havia preservado também o cabeçalho `1.12.100`. A REV3 mantém somente
`## 1.12.101`. Nenhum código funcional, dispatch, retry, cortina ou OCPP foi alterado.

### 1.12.101 REV5 — varredura completa dos contratos de distribuição

Após a REV4, foi identificado que o problema era o processo de preparação do
release: contratos históricos de distribuição estavam sendo descobertos
sequencialmente pela suíte ampla.

Antes de continuar, foram revisados no GitHub os contratos:
- test_prebuilt_distribution_1_12_31.py
- test_prebuilt_distribution_1_12_32.py
- test_prebuilt_distribution_1_12_33.py
- test_prebuilt_distribution_1_12_34.py
- test_prebuilt_distribution_1_12_42.py
- test_prebuilt_distribution_1_12_43.py
- test_prebuilt_distribution_1_12_44.py
- test_release_publication_gate_1_12_41.py
- .github/scripts/validate_repository.py

O CHANGELOG 1.12.101 passa a preservar simultaneamente:
1. exatamente um cabeçalho `## 1.12.101`;
2. a frase histórica de distribuição `pré-compilada`;
3. publicação em duas fases;
4. resumo do diagnóstico das quatro janelas.

A REV5 executa todos os contratos script-style de distribuição individualmente
antes da suíte ampla. Nenhuma mudança funcional adicional foi feita em janelas,
dispatch, retry, cortina ou OCPP.

## Gateway 1.12.102 — prioridade do estado binário das janelas

Campo da 1.12.101: quatro janelas fisicamente abertas, porém o Leap Hub mostrou
somente duas. O log registrou front_left/front_right=true e rear_left/rear_right=false,
com percentuais traseiros 0.0.

A causa no código era a prioridade incorreta: percentual presente era usado antes
do sinal binário dedicado. A 1.12.102 inverte essa prioridade e amplia o diagnóstico
para os oito IDs numéricos de janela documentados na leapmotor-api v0.3.2.

Nenhum comando físico, retry, cortina ou OCPP foi alterado.

## Gateway 1.12.103 — clima e conforto

Evidência de campo da 1.12.102:
- qualquer modo no `prepare_car` terminava em AUTO por `operate=auto` fixo;
- `windshield_defrost` não teve efeito físico mesmo com retorno concluído da biblioteca;
- volante e retrovisores receberam ACK de nuvem/result_timeout, sem efeito físico;
- o Site pode mostrar intenção recente antes de uma telemetria física nova.

1.12.103 corrige AUTO/MANUAL e adiciona `CLIMATE_COMFORT_DIAG` com campos tipados,
sem raw e sem dados sensíveis. Não adiciona retry, não muda as rotas físicas dos
três controles e preserva janelas 1.12.102, cortina e OCPP.

Próximo teste: acionar volante, retrovisores e desembacador dentro do próprio carro
e comparar as linhas `CLIMATE_COMFORT_DIAG`. Isso decide se o defeito restante
está na telemetria Leapmotor ou apenas na reconciliação do Site.

### 1.12.103 REV3 — contrato histórico HOT=AUTO corrigido

A primeira validação ampla da 1.12.103 passou 491 testes e encontrou somente um
contrato histórico da 1.12.58 que ainda exigia `climate_mode=hot` com
`operate=auto`. Esse era exatamente o comportamento funcional que a 1.12.103
corrige.

A REV2 tentou atualizar o bloco inteiro por igualdade textual e falhou por
variação de quebra de linha no worktree Windows. A REV3 usa patch estrutural
restrito à função `test_prepare_car_builds_only_the_requested_dimensions`,
independente de CRLF/LF, e altera somente a expectativa `auto` -> `manual`.

O teste novo da 1.12.103 continua cobrindo separadamente que AUTO permanece AUTO.
Nenhum código funcional adicional foi alterado nesta REV3.

## Gateway 1.12.104 — diagnóstico raw clima/conforto

A 1.12.103 não mostrou `CLIMATE_COMFORT_DIAG` no teste físico.
A 1.12.104 acrescenta somente IDs raw allow-listed de clima/conforto para
descobrir se o C10 publica as mudanças mesmo quando os campos tipados vêm vazios.
Sem alteração física de comandos/retry/janelas/cortina/OCPP.

### Gateway 1.12.104 REV2 — contratos de distribuição

A primeira tentativa da 1.12.104 passou 68 testes direcionados e falhou na coleta da suíte ampla por três contratos de distribuição, antes de qualquer commit/push.

Causas:
- test_prebuilt_distribution_1_12_31.py exige que o CHANGELOG declare que a distribuição continua pré-compilada;
- test_prebuilt_distribution_1_12_32.py e _33.py exigem GITHUB-RECOVERY-<RELEASE_TARGET>.md.

A REV2 corrige somente esses artefatos/documentação. O runtime raw de clima/conforto não foi alterado. Depois disso todos os contratos test_prebuilt_distribution_*.py são executados explicitamente antes da suíte ampla.

## Gateway 1.12.105 — CLIMATE_RAW_PROBE no ponto comprovado

A 1.12.104 foi confirmada em runtime pelo `/health`, mas o teste físico não
gerou `CLIMATE_COMFORT_DIAG`. No mesmo período, `WINDOW_TELEMETRY_DIAG` apareceu,
provando que o `status.raw` chegou até o trecho das janelas.

A 1.12.105 adiciona um probe RAW independente imediatamente após o diagnóstico
das janelas. Ele registra uma amostra vazia uma vez e depois somente mudanças.
Nenhum comando físico/retry foi alterado.

## Gateway 1.12.106 — hotfix de telemetria contínua

Foi confirmada regressão iniciada na 1.12.103: o diagnóstico tipado de
clima/conforto foi chamado antes da criação local de `seat_state` e
`climate_state`. As coletas chegavam ao carro e aos probes intermediários, mas
`serialize_vehicle()` não concluía; por isso `collection_total` desapareceu e
todos os carros ficaram atrasados no Site.

A 1.12.106 move somente essa chamada para depois da criação dos dois estados.
Nenhum comando físico/retry/janelas/cortina/OCPP foi alterado.

Após publicar/instalar, validar primeiro:
1. retorno de `collection_total`;
2. atualização do cartão de Telemetria contínua;
3. atualização do horário/estado dos veículos;
4. somente depois retomar clima/conforto.

## Gateway 1.12.107 — payload verificado do desembaçador

O C10 confirmou fisicamente MAX do para-brisa com `signal.1945=2`. A tentativa
remota anterior aplicou HOT/32/fan7, mas não ativou `windshield_defrost` porque a
biblioteca 0.3.2 usa `wshld=1` no preset interno. A referência de payloads
verificados do protocolo usa `wshld=2` para WINDSHIELD DEFROST.

A 1.12.107 altera somente esse despacho para enviar explicitamente `wshld=2`.
Nenhum retry/resend novo é criado; `SAFE_STATE_RETRY_COMMANDS` continua somente
com climate_on/climate_off. Quick Heat e demais comandos ficam intactos.

Antes de mesclar/publicar: CI verde e revisão do diff. Depois de instalar, fazer
uma única tentativa física com o veículo parado e confirmar `signal.1945=2` /
`windshield_defrost=true`.

## Gateway 1.12.108 — corrida da agenda FAST pós-comando

Auditoria do caminho Site → worker de comando → trava da conta → arme assíncrono
→ SQLite → scheduler → telemetria → fila de eventos → Site encontrou dois
atrasos que podiam esconder a cadência 5/5/8: um poll antigo podia sobrescrever
o agendamento novo após liberar a conta, e um `recovering/error` anterior podia
ser herdado mesmo depois de um comando manual aceito.

A correção é somente de coordenação local. A finalização passa a reler, na mesma
transação, a agenda/proteções vivas e preserva uma confirmação que nasceu depois
do snapshot. Um comando aceito pode cortar `recovering/error`, mas nunca
`cooldown` ou `auth_required`. Se um cooldown/auth surgir enquanto um poll antigo
termina, ele prevalece.

Congelado: payloads, retries físicos, 5/5/8, backoff 8/15/25/40/60/90, janelas,
cortina, capô, OCPP, HMAC e contrato do Site. Antes de merge: revisar diff e CI
verde. Depois de publicar/instalar, homologar apenas o tempo de confirmação com o
veículo estacionado; nenhum reenvio físico adicional faz parte desta release.
