# Leap Hub Gateway 1.12.99 — diagnóstico de campo da cortina por posição

Base obrigatória: `00e04720bf7c444c564c718600ae722fa6bb2a46` (1.12.98 publicada e homologada para uso geral).

## Objetivo

Instrumentar `sunshade_position` para descobrir, sem alterar o comportamento físico,
como o C10 interpreta os valores intermediários do `cmdId=240` e se uma segunda
intenção durante o movimento funciona como pausa/stop.

## O que muda

- antes da única transmissão já existente, registra apenas `pedido_site` e
  `valor_nativo` (0-10);
- a cada amostra de confirmação FAST, registra `esperado_telemetria`,
  `sunshade_percent` observado e `match`;
- os logs não incluem VIN, conta, token, PIN, cookie, cabeçalho ou resposta bruta.

## O que NÃO muda

- fórmula física: `(percent + 5) // 10`;
- método físico: `control_sunshade(... value=str(native))`;
- exatamente uma transmissão por intenção;
- `sunshade_position` continua fora de ACK-first;
- nenhum retry físico é adicionado;
- `SAFE_STATE_RETRY_COMMANDS` continua somente clima on/off;
- matcher da 1.12.98 permanece exato no degrau efetivo;
- supersessão de intenções permanece igual;
- Official diário, clima, trunk, janelas, imagem, OCPP, HMAC, sessão por conta,
  Trips/ABRP/Site e Produção permanecem congelados.

## Teste de campo previsto

Com o carro parado e a cortina inicialmente fechada:
1. enviar 100% uma vez;
2. enquanto ela estiver fisicamente em movimento, repetir 100% uma única vez;
3. observar se para/pausa, continua ou reinicia;
4. somente depois repetir o experimento com 50%.

Não fazer rajada de comandos. A conclusão será baseada em `SUNSHADE_DIAG` +
observação física.
