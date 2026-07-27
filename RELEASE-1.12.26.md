# Leap Hub Gateway 1.12.26 — diagnóstico seguro do Sentinela

- mantém os 25 comandos estáveis e os 2 comandos experimentais isolados;
- não reenvia `sentry_on`/`sentry_off` quando a confirmação remota fica ambígua;
- registra, sem segredos, se a biblioteca retornou normalmente ou se `/remote/ctl/result/query` terminou em timeout/sessão expirada;
- devolve `dispatch_ack`, `remote_result_status`, `confirmation_reason` e `sentry_probe` para o Leap Hub;
- melhora a mensagem do `cmd 220` para diferenciar entrega à nuvem de confirmação por telemetria;
- preserva PIN, tokens, certificados e credenciais fora dos logs.
