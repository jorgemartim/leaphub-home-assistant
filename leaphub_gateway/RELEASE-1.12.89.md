# Leap Hub Gateway 1.12.89 — bounded telemetry cloud reads

Base pública obrigatória: `0627408df89ff5939c1de7640340fec582e2e95b`
(`chore(gateway): publish 1.12.88 [gateway-published]`).

O log de campo da 1.12.88 mostrou um comando `climate_on` aguardando cerca de 25s pela trava da conta enquanto o ocupante era a telemetria. A 1.12.88 já havia removido o retry invisível do status, mas a lista de veículos e a leitura de mensagens ainda usavam os wrappers públicos da leapmotor-api 0.3.2.

Esses wrappers podem executar token refresh, cair para login completo e repetir a chamada antes de devolver o controle ao Gateway. A 1.12.89 aplica o mesmo padrão cooperativo e limitado às três leituras automáticas: lista, status e mensagens.

Não há segundo cliente, concorrência do mesmo cliente, nova tentativa física de comando, terceiro `climate_off`, wake artificial ou aumento de polling.

`config.yaml` permanece 1.12.88 no commit funcional e é promovido para 1.12.89 apenas pelo GitHub Actions após validate/build/smoke/GHCR.
