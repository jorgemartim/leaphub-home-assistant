## 1.12.81

Resposta rápida completa dos controles sem desfazer a correção física do C10.

A distribuição permanece pré-compilada no GHCR oficial e mantém a publicação em duas fases.

- climate_off entra no ACK-first preservando `ac_switch` + `operate=off`;
- a verificação protegida do OFF vira uma única leitura curta depois do ACK, sem laço síncrono adicional;
- se a leitura ainda contradiz o OFF, a segunda e última transmissão repete exatamente o mesmo estado e também usa ACK-first;
- depois da segunda transmissão a confirmação final fica com a telemetria FAST já existente;
- lock, unlock, climate_on, quick_cool e quick_heat mantêm o ACK-first da 1.12.80;
- o anúncio imediato Gateway -> Site da 1.12.78 permanece e agora registra no log se o atalho foi aceito;
- nenhuma terceira transmissão, nenhum aumento de polling e nenhuma alteração de autenticação/sessão.

Ver RELEASE-1.12.81.md.
