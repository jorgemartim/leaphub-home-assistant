# Leap Hub Gateway 1.12.100

## Janelas C10/B10

Medição física em 16/08/2026 no C10 do proprietário:
- `value=0` fechou todas as janelas;
- `value=10` abriu até próximo/fim de curso observado;
- `value=100`, default da biblioteca para abrir, era aceito pela nuvem mas não executado pelo carro.

A interface permanece `0%, 10%, ... 100%`. Somente C10/B10 convertem a escrita para `0..10`.
T03 e modelos desconhecidos permanecem em `0..100`.

`windows_open` envia `10` em C10/B10; `windows_close`, `0`. Sem retry novo.

## Confirmação

`windows_position` passa a ser confirmável por FAST telemetry e participa da mesma família de
supersessão de abrir/fechar. Abrir/fechar deixa de aceitar "qualquer janela aberta" como sucesso:
as quatro precisam concordar com o estado-alvo.

Quando a FAST prova o estado físico, o Gateway anuncia o veredito final ao endpoint interno de
resultados, permitindo que o botão saia de pendente sem F5 e sem novo comando físico.

## Preservado

- `SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}`;
- `sunshade_position` sem mudança;
- cadência FAST `5/5/8`, depois `24/34/45/60/90`, sem mudança;
- site Produção sem alteração neste pacote;
- OCPP sem mudança funcional.

## Validação

No Windows, dois testes históricos têm cleanup SQLite incompatível e podem gerar WinError 32.
A REV3 ignora somente esses dois localmente. O GitHub Actions roda o validador oficial completo
em `ubuntu-latest` antes de construir, publicar GHCR e promover `config.yaml`.

## Correção REV4 de empacotamento

O contrato de runtime da imagem em `Dockerfile` também foi elevado para
`leaphub_official_trip_probe.PROBE_VERSION == "1.12.100"`. O módulo Python já
estava em 1.12.100; faltava alinhar a asserção do autoteste da imagem.

O teste `test_ocpp_sqlite_single_writer_1_12_45.py` permanece inalterado. Ele é
uma falha histórica conhecida somente no Windows; a CI Linux continua sendo a
validação autoritativa desse contrato.
