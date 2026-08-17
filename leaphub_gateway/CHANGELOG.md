## 1.12.103

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- corrige `Preparar o carro`: AUTO continua AUTO, enquanto resfriar/aquecer/ventilar usam operação MANUAL em vez de serem forçados para AUTO;
- preserva temperatura e ventilação solicitadas no pacote experimental de preparação;
- adiciona `CLIMATE_COMFORT_DIAG`, limitado aos estados tipados de clima, desembacador, volante e retrovisores;
- o diagnóstico não percorre `status.raw` e não registra VIN, conta, GPS, credenciais ou payload remoto;
- desembacador, volante e retrovisores continuam sem retry físico automático: ACK da nuvem não vira confirmação do carro;
- preserva integralmente as correções das quatro janelas da 1.12.102, cortina e OCPP.
