## 1.12.79

Distribuição pré-compilada preservada, com publicação em duas fases.

Climatização C10/B10/B05 alinhada ao estado físico observado.

- AUTO usa o payload completo do cmd 170 com `operate=auto` e `mode=nohotcold`.
- OFF usa `ac_switch` com `operate=off`.
- A confirmação distingue OFF, AUTO, resfriamento e aquecimento por `climate_mode`.
- A segunda transmissão protegida repete exatamente o mesmo estado; continuam no máximo duas transmissões.
- Sem aumento de polling e sem alteração funcional de OCPP, fila ou comandos de movimentação.

Ver RELEASE-1.12.79.md.
