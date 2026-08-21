# 1.12.125

## Prioridade real para comandos após sessão fria

A telemetria declarava um teto de 4 segundos por chamada automática, porém a
fábrica compartilhada do cliente Leapmotor impunha um piso de 12 segundos.
Durante uma autenticação automática fria, esse piso podia reter a trava da
conta por várias chamadas consecutivas e atrasar um comando do usuário por
dezenas de segundos.

Esta versão permite que a telemetria use efetivamente o teto de 4 segundos. Os
comandos continuam recebendo o timeout maior somente no trecho de despacho, e
a telemetria continua sendo a fonte autoritativa da confirmação física.

## Segurança e dados

- nenhum retry físico novo foi adicionado;
- um gesto continua produzindo no máximo um despacho físico;
- nenhuma migration, limpeza, exclusão, backfill ou recálculo é executado;
- `config.yaml` permanece em 1.12.124 até o CI publicar e validar a imagem
  1.12.125 anonimamente no GHCR.
