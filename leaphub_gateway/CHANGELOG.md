## 1.12.90

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- confirmação física de AUTO/COOL/HEAT passa a exigir o modo HVAC, não apenas `climate_on=true`;
- `quick_heat` não pode mais ser marcado como confirmado enquanto a telemetria ainda informa resfriamento;
- normalização aceita os modos numéricos validados no C10 e sinais textuais alternativos para outros modelos;
- modo desconhecido em veículo futuro fica inconclusivo em vez de produzir confirmação falsa;
- `climate_off` continua confirmado pelo switch desligado;
- `climate_details` passa a transportar também `ac_cooling_and_heating` sem nova chamada de rede;
- dispatch, payload C10, ACK-first, duas tentativas máximas de OFF, polling, sessão persistente e bounded reads permanecem inalterados.
