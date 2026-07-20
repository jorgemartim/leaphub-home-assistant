# Leap Hub Gateway 1.11.98

## Confirmação física dos controles

- Um comando aceito pela nuvem não é mais tratado automaticamente como aplicado no veículo.
- `climate_off`, `climate_on`, `quick_cool` e `quick_heat` terminam como `not_applied` quando uma leitura nova e avaliável contradiz o estado solicitado.
- `not_applied` é um estado terminal separado de falha de conexão e separado de `sent`.
- O Gateway não realiza uma terceira tentativa automática após a repetição segura.
- O diário persistente preserva `cloud_accepted`, `vehicle_confirmed`, `not_applied`, `applied` e `final_outcome`.
- O log do worker informa o resultado final sem registrar e-mail, VIN, PIN, token ou credencial.

Nenhuma alteração de configuração é necessária.
