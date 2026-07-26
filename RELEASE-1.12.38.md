# Leap Hub Gateway 1.12.38

Correção incremental de estabilidade e observabilidade sobre a 1.12.37.

O circuit breaker global não volta mais a `healthy` por dois sucessos consecutivos da mesma conta. A recuperação antecipada exige uma janela sem novas falhas e sucesso de duas contas distintas. Se houver somente uma conta, o período degradado expira normalmente; comandos manuais nunca são bloqueados.

O campo legado `queue_wait_seconds` agora representa somente a espera pela conta e pela vaga do Connector. O resultado também expõe fases com nomes claros sem inventar uma separação que a biblioteca pública ainda não fornece: o resultado remoto permanece marcado como agregado ao despacho.

Nenhum método físico, retry, endpoint REST, sessão, intervalo de telemetria, OCPP ou Event Transport foi alterado.
