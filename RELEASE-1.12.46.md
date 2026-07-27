# Leap Hub Gateway 1.12.46

## Isolamento de capacidade por conta

- Corrige a inversão de ordem entre a trava da conta e a vaga global do Connector na telemetria.
- A telemetria agora adquire `account lock -> connector slot`, igual aos comandos e sincronizações.
- Uma conta ocupada não mantém uma vaga global presa enquanto espera sua própria operação terminar.
- A espera por vaga é fatiada para que um comando manual da mesma conta preempte a telemetria rapidamente.
- Métricas agregadas mostram espera da conta, espera do Connector, yields e timeouts sem PII.
- O painel Ingress passa a exportar diagnóstico JSON sanitizado, sem logs, tokens, segredos, URLs, VIN ou identidade de wallbox.
- Nenhuma migration destrutiva; filas, SQLite, sessões, rotas e credenciais existentes são preservados.
