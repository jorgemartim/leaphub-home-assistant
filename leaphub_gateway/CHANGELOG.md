## 1.12.109

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- adiciona OFF do desembaçador no MESMO comando público `windshield_defrost`, usando `enabled=false` e alterando somente `wshld` de `2` para `0`; a matriz permanece 40 estáveis + 12 experimentais;
- adiciona confirmação FAST do `prepare_car` por climatização ligada, modo, temperatura e ventilação na mesma amostra nova;
- remove uma passagem redundante de supersessão/lock quando a confirmação já está pendente;
- adiciona `CONFIRM_ARM_DIAG` para localizar contenções residuais sem mudar cadência, timeout ou quantidade de leituras;
- mantém `SAFE_STATE_RETRY_COMMANDS` somente em `climate_on`/`climate_off`;
- mantém `wshld=2` do ON, janelas, cortina, capô e OCPP congelados;
- mantém `config.yaml` em 1.12.108 até publicação normal via CI/GHCR.
