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
