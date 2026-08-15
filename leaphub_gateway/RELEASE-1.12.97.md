# Leap Hub Gateway 1.12.97 — hotfix de empacotamento Official

Base obrigatória: `215c4215d58ce3e2439c1bb2dcec0041995414c4` (1.12.96 publicada).

## Falha de campo comprovada

A primeira sonda real `POST /v1/vehicles/driving-record` terminou em ~0,12 s com HTTP 500.
O traceback mostrou `ModuleNotFoundError: No module named 'official_trip_probe'` dentro de
`leaphub_telemetry_engine.py`, antes de qualquer POST à Leapmotor.

## Correção

- `official_trip_probe.py` passa a ser instalado em `site-packages` como `leaphub_official_trip_probe.py`;
- `TelemetryEngine.execute_driving_record_probe()` importa primeiro o nome runtime e usa o arquivo local apenas como fallback;
- o autoteste da imagem passa a importar o nome runtime real;
- um teste cumulativo impede regressão do contrato de empacotamento.

## Congelado

Nenhuma lógica de comando físico, confirmação 5/5/8, `climate_off`, trunk/sunshade,
telemetria, imagem, HMAC, OCPP ou Site é alterada.

## Homologação após publicar

Instalar 1.12.97 no Gateway Beta/Staging e executar uma única sonda Official read-only
na mesma conta C10. Somente depois de resposta redigida válida avaliar o schema.
