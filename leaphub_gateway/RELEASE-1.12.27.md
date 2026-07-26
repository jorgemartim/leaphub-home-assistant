# Leap Hub Gateway 1.12.27 — evidência segura do Sentinela

- registra somente campos de status allow-listados do retorno da biblioteca;
- separa “método concluiu sem exceção” de “estado físico confirmado”;
- devolve `remote_result_evidence`, `remote_result_signal` e `remote_result_summary` ao Leap Hub;
- nenhum token, PIN, certificado, VIN ou identificador remoto completo é incluído no diagnóstico;
- `sentry_on` e `sentry_off` continuam experimentais, owner-only no site e sem retry automático.
