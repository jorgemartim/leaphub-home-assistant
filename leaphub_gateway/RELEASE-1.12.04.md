# Leap Hub Gateway 1.12.04

- Corrige o desligamento real da climatização no Leapmotor C10.
- O comando de desligar passa a usar `ac_switch` com `operate=close` e o modo HVAC observado na telemetria.
- Mantém uma segunda tentativa protegida e idempotente apenas quando uma leitura fresca confirma que o ar continua ligado.
- Reconhece desembaçamento ativo como perfil de aquecimento para montar o fechamento correto.
- Expõe no resultado apenas a estratégia e o perfil não sensível usados, facilitando diagnóstico sem registrar PIN ou credenciais.
- Não altera OCPP, filas persistentes ou promoção Beta/Produção.
