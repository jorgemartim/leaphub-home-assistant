# Leap Hub Gateway 1.11.86

Refinamento dos comandos remotos após o teste real de climatização.

- mantém HTTP/2 e as correções de transporte da 1.11.85;
- verifica o estado real após `climate_on` e `climate_off`;
- se o carro apenas acordar e o estado continuar oposto, repete uma única vez somente a ação idempotente;
- nunca repete destravamento, aberturas ou outros comandos sensíveis;
- amplia a janela rápida de telemetria para 180 segundos;
- melhora os logs de conta, veículo-alvo, tentativas e confirmação.
