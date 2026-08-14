# Leap Hub Gateway 1.12.86 — correção de regressões da 1.12.85

Base publicada obrigatória: `4e5552f90eb0bb5a849d37f9be6eaf543f196b3d`.

## Evidência de campo

Na 1.12.85 o despacho remoto continuou rápido quando os recursos estavam livres
(~600 ms), mas três gargalos de software apareceram ao redor dele:

1. `lock` registrou `trava_motor=11398ms` com `dispatch=604ms`;
2. após reinício, `unlock` registrou `trava_motor=11476ms`, além do login;
3. em outro comando, a telemetria segurou a conta por mais de 30 s, cedeu em
   ponto seguro, mas o worker ainda aguardou a trava global até o teto e falhou
   antes do envio;
4. falhas assíncronas depois do HTTP 200 eram persistidas no diário, mas não eram
   anunciadas imediatamente ao Site, permitindo controles visualmente presos;
5. uma confirmação de `unlock` chegou a encerrar a janela após 205 s.

## Correções

- preserva o cliente one-shot da 1.12.85, mas restaura refresh de status de forma
  cooperativa e limitada a uma releitura;
- confirmação com sessão expirada agenda reconexão em 3 s, em novo ciclo;
- espera pelo lock interno da sessão durante telemetria é cooperativa: checa
  prioridade manual a cada 250 ms e tem teto de 5 s;
- o SELECT somente-leitura do precheck do comando usa diretamente a conexão WAL,
  sem esperar o lock global do motor; `engine_lock_wait_ms` fica em zero por
  compatibilidade de métricas;
- falha terminal do worker retorna o mesmo payload persistido e o anuncia na hora
  pela rota de resultado de comando, permitindo ao Site liberar os controles.

## Guardrails preservados

- ACK-first;
- payloads Leapmotor C10, inclusive `climate_off` com
  `params={"operate": "off"}`;
- máximo de duas transmissões físicas quando retry é permitido;
- nenhuma terceira transmissão;
- nenhuma segunda sessão Leapmotor concorrente;
- nenhum wake artificial;
- supersessão de confirmações;
- anúncio imediato Gateway→Site;
- `config.yaml` permanece 1.12.85 no commit funcional e só é promovido pelo
  GitHub Actions após validate/build/smoke/GHCR anônimo.
