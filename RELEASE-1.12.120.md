# Leap Hub Gateway 1.12.120 — confirmação rápida de conforto

## Evidência de campo

No teste de 20/08/2026, `quick_heat` foi aceito às 16:11:40.996 e terminou o
despacho em aproximadamente 606 ms. O resultado chegou ao site às 16:11:41.785,
mas o estado físico só foi confirmado às 16:12:22.252: cinco leituras e 40 s.

A transmissão não estava lenta. A escada FAST fazia leituras em 0/5/10/18 s e
depois saltava para cerca de 42 s. O novo estado foi publicado pelo carro nesse
intervalo e só pôde ser observado ao fim do salto.

## Correção segura

Clima, desembaçador dianteiro, aquecimento do volante e dos retrovisores recebem
uma escada de confirmação própria: 5/5/8/10/10/12/24/34/45/60/90 s. Assim, as
leituras iniciais ocorrem em aproximadamente 0/5/10/18/28/38/50 s, com intervalo
máximo de 12 s até 50 s.

Isto altera somente releituras de telemetria depois de um comando já aceito:

- não repete nem reenvia comando físico;
- não muda payload, PIN, autenticação, direito ou timeout de despacho;
- não transforma ACK da nuvem em sucesso físico;
- não reduz o prazo de confirmação nem o teto de segurança;
- não muda a cadência homologada de trava, vidros, cortina, porta-malas e recarga.

## Dados preservados

Não há migration, alteração de schema, limpeza, exclusão ou recálculo. Banco,
fila, histórico, Trips, OCPP e dados já coletados permanecem intactos.

`config.yaml` permanece em 1.12.119 no candidato. A promoção para 1.12.120 só
ocorre depois do CI verde, smoke test e acesso anônimo da imagem GHCR confirmado.
