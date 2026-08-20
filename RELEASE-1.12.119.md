# Leap Hub Gateway 1.12.119 — payloads verificados de conforto

## Evidência de campo

Em 20/08/2026, o C10 recebeu uma única tentativa de `steering_wheel_heat_on`.
A `leapmotor-api` 0.3.2 concluiu sem exceção, porém o volante não aqueceu e a
telemetria permaneceu em `steering_wheel_heating=0` / `signal.1816=0`.

A biblioteca enviava o envelope legado `{"value":"on"}`. A implementação
verificada do aplicativo internacional usa `{"level":"2"}` para ligar e
`{"level":"1"}` para desligar o volante. Para os retrovisores, usa
`{"value":"2"}` e `{"value":"1"}`.

## Correção

O gateway sobrescreve somente o `cmd_content` desses quatro comandos, mantendo
os mesmos IDs, direitos, PIN, autenticação e fluxo remoto da biblioteca:

- volante: cmd 320, ON `level=2`, OFF `level=1`;
- retrovisores: cmd 440, ON `value=2`, OFF `value=1`.

Se o primitivo instalado não aceitar o override, o gateway falha fechado e não
volta ao payload legado. Cada intenção continua gerando uma única transmissão,
sem retry e sem transformar ACK da nuvem em sucesso físico.

## Preservado

Nenhum schema, banco, fila, dado coletado, migration, recálculo ou exclusão é
alterado. Clima, desembaçador dianteiro, janelas, cortina, Trips, OCPP,
proximidade e cadências permanecem iguais à 1.12.118.

`config.yaml` permanece em 1.12.118 até o CI construir e publicar a imagem
1.12.119 com smoke test e acesso anônimo confirmados.
