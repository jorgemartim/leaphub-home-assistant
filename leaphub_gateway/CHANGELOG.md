## 1.12.80

Retorno rápido restaurado sem desfazer a correção física da climatização C10.

A distribuição permanece pré-compilada no GHCR oficial; esta versão preserva o fluxo de publicação em duas fases.

- lock, unlock, climate_on, quick_cool e quick_heat param de esperar o polling síncrono de resultado da leapmotor-api 0.3.2;
- o ACK da escrita remota vira `ack_only`/`confirmation_pending` e a confirmação física continua pela telemetria FAST;
- o payload AUTO `operate=auto` + `mode=nohotcold` da 1.12.79 permanece;
- climate_off permanece no fluxo 1.12.79 nesta rodada para não mexer no retry protegido antes de novo teste físico;
- nenhuma terceira transmissão e nenhum aumento de polling.

Ver RELEASE-1.12.80.md.
