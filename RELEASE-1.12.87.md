# Leap Hub Gateway 1.12.87 — restauração da 1.12.84 conhecida

## Base funcional

`27b8129b26d71cacf0df5ceb2547eafc75803f4d`

Publicação original:

`chore(gateway): publish 1.12.84 [gateway-published]`

## Base pública anterior

`47deee4c052c79f070722df44d4f0cd67dc26705`

Gateway 1.12.86.

## Motivo

Os testes de campo posteriores mostraram regressões ao redor do dispatch:
- espera da conta chegando a dezenas de segundos;
- comando falhando antes de chegar ao veículo;
- confirmações permanecendo abertas por mais de 200 segundos.

A 1.12.87 não redesenha novamente essa arquitetura.

Ela restaura a última base funcional conhecida.

## Regra de equivalência

Os arquivos:
- connector.py
- connector_server.py
- gateway_manager.py
- ocpp_gateway.py
- privacy.py
- telemetry_engine.py

foram restaurados diretamente do commit publicado da 1.12.84.

A única diferença permitida é o marcador da versão 1.12.87.

## Site

Nenhuma alteração.

Site permanece em 1.12.358.

## Publicação

config.yaml permanece 1.12.86 no commit funcional.

A promoção para 1.12.87 pertence exclusivamente ao GitHub Actions após validate, build, smoke e validação anônima do GHCR.
