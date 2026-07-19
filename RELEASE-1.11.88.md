# Leap Hub Gateway 1.11.88

- corrige `NameError: name 'LOG' is not defined` durante a confirmação de comandos;
- o logger passa a ser inicializado e usado em modo best-effort, sem interromper a ação;
- falhas ao registrar diagnóstico nunca mais substituem o erro original;
- `climate_on` e `climate_off` recebem uma única repetição protegida quando o veículo acorda, mas a leitura de confirmação fica indisponível;
- mantém a sessão autenticada, o bloqueio por conta e a proteção contra duplicidade;
- registra separadamente falha de leitura e falha da repetição idempotente.
