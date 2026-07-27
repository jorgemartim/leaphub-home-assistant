## 1.12.47

- Circuit breaker por conta: uma conta lenta/falhando reduz somente a própria telemetria de fundo.
- Degradação global exige falhas de contas distintas.
- Sondas de recuperação e trabalho secundário respeitam o escopo da conta.
- Comandos manuais continuam prioritários e não são bloqueados pelo breaker.
- Diagnóstico agregado informa backpressure sem identificadores pessoais.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
