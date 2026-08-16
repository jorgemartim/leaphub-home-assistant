# GITHUB RECOVERY — Gateway 1.12.99

- Base obrigatória: `00e04720bf7c444c564c718600ae722fa6bb2a46` (1.12.98 publicada).
- Se o clone local ainda estiver no commit funcional `fa3a6fb86aa515c4bbc527c5ef8ce516e4ff84e4`,
  o publisher permite somente fast-forward para a promoção `00e04720bf7c444c564c718600ae722fa6bb2a46`.
- `config.yaml` permanece 1.12.98 no commit funcional; o Actions promove
  para 1.12.99 apenas após build, smoke e GHCR público.
- Nunca usar `reset --hard`, rebase ou force push.
- A 1.12.99 é diagnóstico observacional: não mudar a conversão, payload,
  número de transmissões, matcher ou retry durante esta rodada.
- Após push, aguardar `chore(gateway): publish 1.12.99 [gateway-published]`
  antes de instalar.
