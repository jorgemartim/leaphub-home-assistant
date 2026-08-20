# Leap Hub Gateway 1.12.121 — payload efetivo dos bancos

## Diagnóstico de campo

Em 20/08/2026 foram ensaiadas isoladamente posições numéricas 1, 2 e 3 nos
níveis 1 e 3. A nuvem concluiu os comandos, porém a telemetria permaneceu em
zero e nenhum banco atuou fisicamente. Cada ensaio foi encerrado com nível zero.

A `leapmotor-api==0.3.2` serializa esses comandos como
`{"value":"posição,nível"}`. A implementação C10 atual usa os campos semânticos
`position=driver|copilot` e `level=0..3`. O ACK anterior confirmava apenas que a
nuvem recebeu um JSON válido, não que o carro reconheceu o envelope.

## Correção

- comandos 301 e 370 passam pelo mesmo primitivo remoto já usado com segurança
  nos payloads verificados do volante e dos retrovisores;
- o Gateway envia exatamente `{"position":"driver","level":"3"}` ou o lado
  `copilot`, sempre com nível textual de 0 a 3;
- posição numérica, lado traseiro e nomes não comprovados falham antes da rede;
- os wrappers legados da dependência não são executados nem como fallback;
- a matriz completa cobre 2 comandos × 2 lados × 4 níveis.

## Segurança e dados

Não há migration, alteração de schema, limpeza, exclusão, recálculo ou escrita
retroativa. Telemetria, Trips, OCPP, fila, sessões e dados já coletados permanecem
inalterados. Clima, desembaçador, volante e retrovisores não mudam.

`config.yaml` permanece em 1.12.120 no candidato. A promoção para 1.12.121 só
ocorre após testes, build, smoke test e confirmação de acesso anônimo ao GHCR.
