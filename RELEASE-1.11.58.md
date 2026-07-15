# Leap Hub Gateway 1.11.58

Esta versão transforma a telemetria visual em um contrato versionado entre o Home Assistant e o Leap Hub.

## Alterações

- `visual_primary_state`: estado principal do carro.
- `visual_components`: lista ordenada de aberturas, luzes, sentinela e carga.
- `visual_signature`: chave estável para escolher uma imagem exata.
- `visual_capabilities`: informa quais sensores responderam, sem tratar ausência como fechado.
- `visual_state_version`: versão 2 do formato visual.

O formato anterior continua sendo enviado dentro de `visual_state`, mantendo compatibilidade.
