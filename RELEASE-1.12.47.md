# Leap Hub Gateway 1.12.47

## Circuit breaker isolado por usuário

- Corrige um ponto de isolamento: falhas repetidas de uma única conta não podem mais colocar todo o ambiente em modo degradado.
- Adiciona backpressure local por conta para telemetria automática e trabalho secundário.
- O breaker global agora exige evidência de contas distintas na mesma janela antes de reduzir a cadência compartilhada.
- Comandos manuais continuam fora do circuit breaker e preservam prioridade.
- Sondas de recuperação são independentes por conta; uma conta em recuperação não consome a vez das demais.
- Diagnóstico expõe apenas contagens agregadas de contas em backpressure, sem e-mail, VIN, account_id bruto ou credenciais.
- Sem migration destrutiva e sem reset de sessões, filas, veículos ou wallboxes.
