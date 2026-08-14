# Leap Hub Gateway 1.12.93 — arme de confirmação fora do caminho crítico

Base publicada obrigatória: **1.12.92**
(`ce84114635f607bef170897ab8c48843c42c8b55`).

## Problema comprovado

Na 1.12.92, o dispatch físico já voltava em ~0,6 s (ou ~2,5 s no
`climate_off` com duas transmissões), mas `_arm_command_confirmation()` ainda
rodava antes de `TelemetryEngine.execute_command()` retornar. Como esse arme
usa `self.lock`/SQLite, logs de campo mediram 6,8 s, 13,4 s, 13,6 s, 14,1 s,
16,2 s e 22,8 s somente nessa etapa. Enquanto isso, o Connector mantinha a
trava da conta e a vaga global, e o Site ainda não recebia o resultado.

## Correção estrita

A 1.12.93 cria um único executor FIFO para o bookkeeping de confirmação.
Depois de `connector.handle_command()` retornar uma ação aceita, o caminho
crítico apenas copia metadados não sensíveis e enfileira o job. O resultado
retorna imediatamente; supersessão e `boost(profile="command")` são persistidos
pelo worker local em ordem.

A fila NÃO recebe:
- `LeapmotorApiClient`;
- sessão/token;
- credenciais;
- callback de dispatch;
- método de comando físico.

Falha local no arme não gera retry físico.

## Fora do escopo deliberadamente

Não são alterados nesta release:
- composição/serialização visual lenta em cold start;
- matcher de `climate_off`;
- payload/método de porta-malas ou cortina;
- polling/cadência;
- timeouts;
- Site/PWA.

Esses pontos continuarão sendo medidos separadamente para evitar regressão
causada por correções misturadas.

## Guardrails congelados

- runtime restaurado da 1.12.84 via 1.12.87;
- status cooperativo 1.12.88;
- bounded list/status/messages 1.12.89;
- confirmação física AUTO/COOL/HEAT 1.12.90;
- precheck sem trava global 1.12.91;
- ACK pós-dispatch sem bookkeeping de auth redundante 1.12.92;
- ACK-first;
- C10 `climate_off` `operate=off`;
- no máximo duas transmissões seguras OFF;
- supersessão;
- uma sessão persistente, sem segundo cliente;
- nenhum wake artificial.
