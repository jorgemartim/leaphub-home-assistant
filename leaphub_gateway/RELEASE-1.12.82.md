# Leap Hub Gateway 1.12.82 — prioridade manual sem starvation

Base: **1.12.81 publicada**.

## Evidência de campo

Na 1.12.81, o cloud dispatch ficou rápido depois do ACK-first, mas duas ações manuais foram medidas esperando a trava da conta por aproximadamente 25,8s e 20,5s. A ocupante era a thread de telemetria. Outro `climate_on` sem fila gastou cerca de 2,5s somente em `account_auth_status`, antes de um dispatch de ~0,6s.

## Correção

- Toda chamada automática de rede feita pela telemetria empresta um teto curto de **4s** enquanto possui a conta. O timeout original do cliente é restaurado em `finally`.
- A sessão criada por origem `telemetry` nasce com esse teto; sessões criadas por `command` continuam usando o timeout configurado.
- Lista de veículos, mensagens e status verificam novamente a presença de comando manual depois da chamada. Se a ação chegou durante um timeout/retorno, a coleta termina como `TelemetryYieldForManual`, sem destruir uma sessão válida por causa da preempção.
- `account_auth_status()` passa a usar a leitura concorrente do SQLite/WAL sem `self.lock`. `begin_account_auth()` e demais mutações permanecem sob lock/`BEGIN IMMEDIATE`.

## Guardrails preservados

- `lock`, `unlock`, `climate_on`, `climate_off`, `quick_cool`, `quick_heat`: ACK-first.
- C10 OFF: `ac_switch({"operate":"off"})`.
- C10 AUTO: `operate=auto`, `mode=nohotcold`, payload completo preservado.
- `climate_off`: no máximo duas transmissões idênticas; nunca terceira.
- Sem aumento de polling.
- Sem mudança no armazenamento de credenciais ou no reuso de sessão.
- `config.yaml` permanece 1.12.81 no commit funcional; promoção para 1.12.82 só após build/smoke/GHCR público.
