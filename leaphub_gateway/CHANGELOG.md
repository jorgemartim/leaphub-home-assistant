## 1.12.107

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- corrige somente o payload de `windshield_defrost` do cmd 170;
- envia explicitamente HOT + MANUAL + 32 °C + fan 7 + `wshld=2`, conforme payload verificado do protocolo;
- preserva `quick_heat`, AUTO, OFF, temperaturas, fan e demais comandos;
- `SAFE_STATE_RETRY_COMMANDS` continua exclusivamente `climate_on`/`climate_off`;
- o desembaçador não ganha retry/resend nem entra em ACK-first;
- nenhuma alteração em janelas, cortina, capô ou OCPP.
