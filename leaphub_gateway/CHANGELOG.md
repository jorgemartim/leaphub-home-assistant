## 1.12.80

Retorno rápido restaurado sem desfazer a correção física da climatização C10.

- lock, unlock, climate_on, quick_cool e quick_heat param de esperar o polling síncrono de resultado da leapmotor-api 0.3.2;
- o ACK da escrita remota vira `ack_only`/`confirmation_pending` e a confirmação física continua pela telemetria FAST;
- o payload AUTO `operate=auto` + `mode=nohotcold` da 1.12.79 permanece;
- climate_off permanece no fluxo 1.12.79 nesta rodada para não mexer no retry protegido antes de novo teste físico;
- nenhuma terceira transmissão e nenhum aumento de polling.

Ver RELEASE-1.12.80.md.

## 1.12.79

Distribuição pré-compilada preservada, com publicação em duas fases.

Climatização C10/B10/B05 alinhada ao estado físico observado.

- AUTO usa o payload completo do cmd 170 com `operate=auto` e `mode=nohotcold`.
- OFF usa `ac_switch` com `operate=off`.
- A confirmação distingue OFF, AUTO, resfriamento e aquecimento por `climate_mode`.
- A segunda transmissão protegida repete exatamente o mesmo estado; continuam no máximo duas transmissões.
- Sem aumento de polling e sem alteração funcional de OCPP, fila ou comandos de movimentação.

Ver RELEASE-1.12.79.md.
