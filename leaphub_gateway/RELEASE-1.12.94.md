# Leap Hub Gateway 1.12.94 — isolamento de controle, telemetria e imagem

Base publicada obrigatória: **1.12.93**
(`47d0d0331ed277750e1ea45128a6ca5d436727dd`).

## Evidência de campo

Na 1.12.93 os controles estabilizaram no caminho crítico, mas o cold start ainda
mostrou `serialize_vehicle` em aproximadamente 40–44 s. A imagem oficial era
composta dentro da serialização protegida e a primeira imagem do processo ainda
podia gerar uma galeria de diagnóstico com múltiplas conversões WebP.

## Correção

- telemetria serializa estado sem imagem dentro da sessão protegida;
- o evento de estado é persistido antes de qualquer render;
- imagem passa para um único worker local separado;
- o worker recebe somente snapshot JSON e nunca recebe cliente, token,
  credenciais, callback de comando ou sessão;
- o render usa somente o ZIP local (`allow_network=False`);
- mudanças rápidas de estado tornam jobs visuais antigos obsoletos por geração;
- a galeria de diagnóstico só é gerada quando solicitada explicitamente;
- metadados da última imagem são reaproveitados para deduplicação sem carregar
  bytes no caminho de telemetria.

## Guardrails congelados

ACK-first, payload C10, máximo de duas transmissões OFF, porta-malas/cortina sem
retry físico automático, supersessão, uma sessão Leapmotor, bounded reads 4 s,
modo AUTO/COOL/HEAT, precheck sem trava global e arme FIFO 1.12.93 permanecem.
Polling, timeouts e Site não são alterados.
