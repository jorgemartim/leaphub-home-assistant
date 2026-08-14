# Leap Hub Gateway 1.12.92 — ACK pós-dispatch sem bookkeeping redundante

Base publicada obrigatória: **1.12.91**
(`d5cbe8d154f8502ff9a157b0dfc9393e4009641a`).

## Causa comprovada 1 — atraso depois do dispatch

O log de campo da 1.12.91 mostrou `quick_heat` com dispatch de ~0,6 s, mas
11–37 s de tempo não atribuído antes do resultado sair da Gateway.

No runtime 1.12.91, depois de `connector.handle_command()` terminar, o caminho
de sessão reutilizada ainda chamava `record_account_auth_success()`. Essa função
usa a trava global `self.lock` e em seguida limpa cooldown usando a mesma trava.

Nenhum login ocorreu nesse ponto. A 1.12.92 remove apenas essa atualização
redundante. Login real continua registrando sucesso normalmente.

## Causa ainda a medir — telemetria segurando a conta

A 1.12.91 também mostrou um comando esperando ~24 s pela trava da conta enquanto
`leaphub-telemetry-poll_0` já a possuía havia dezenas de segundos.

As leituras cloud da 1.12.89 já são one-shot, limitadas e cooperativas. Alterar
novamente login, sessão ou timeouts sem saber a etapa exata arriscaria regressão.

A 1.12.92 adiciona telemetria de duração somente para etapas lentas:
- espera de `_session_operation_lock`;
- criação do cliente;
- reserva de autenticação;
- escrita local de tentativa;
- `client.login()`;
- bookkeeping de sucesso;
- escrita local de sucesso;
- lista de veículos e refresh;
- mensagens e refresh;
- status e refresh;
- serialização;
- ciclo de coleta total.

Nenhuma dessas medições altera fluxo, timeout, retry ou polling.

## Guardrails congelados

- base funcional restaurada da 1.12.84 via 1.12.87;
- status cooperativo 1.12.88;
- lista/status/mensagens bounded 1.12.89;
- confirmação física AUTO/COOL/HEAT/OFF 1.12.90;
- precheck manual sem trava global 1.12.91;
- ACK-first;
- C10 exato;
- `climate_off` no máximo duas transmissões;
- supersessão;
- uma sessão persistente, sem segundo cliente;
- nenhum wake artificial;
- Site intacto.

`config.yaml` permanece 1.12.91 no commit funcional. A promoção para 1.12.92
fica exclusivamente com o GitHub Actions após validate/build/smoke/GHCR.
