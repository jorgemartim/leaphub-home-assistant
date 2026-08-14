# Leap Hub Gateway 1.12.88 — handoff cooperativo de status

Base pública obrigatória: `11f04b4104ca15d58842501e90074a8b86bd20b4`
(`chore(gateway): publish 1.12.87 [gateway-published]`).

A correção é deliberadamente estreita: somente o status automático deixa de usar
o retry invisível do método público `get_vehicle_status()` da leapmotor-api 0.3.2.

Em expiração de token: uma leitura, no máximo um refresh, no máximo uma
releitura e nunca uma terceira chamada. Entre as etapas a prioridade manual é
consultada. O mesmo cliente e a mesma sessão persistente são preservados.

ACK-first, C10 AUTO/OFF, máximo de duas transmissões, supersessão, anúncio
imediato e polling existente permanecem. Site 1.12.358 intocado.

`config.yaml` permanece 1.12.87 no commit funcional. O GitHub Actions promove
1.12.88 somente depois de validate/build/smoke/GHCR.
