# Leap Hub Gateway 1.12.103 — clima e conforto

## Evidência de campo

Na 1.12.102, `windshield_defrost` chegou à nuvem e a biblioteca terminou sem
exceção, mas o carro não aplicou fisicamente. `steering_wheel_heat_on` e
`rearview_mirror_heat_on` foram aceitos pela nuvem, porém o resultado remoto
ficou inconclusivo (`result_timeout`) e também não houve efeito físico.

Por segurança, esta versão NÃO transforma ACK de nuvem em sucesso físico e NÃO
repete automaticamente nenhum desses comandos.

## Correção objetiva

`prepare_car_parameters()` forçava `operate=auto` para qualquer modo. Agora:
- AUTO/generic/nohotcold -> `mode=wind`, `operate=auto`;
- cold/hot/wind -> `operate=manual`;
- temperatura e nível de ventilação continuam sendo enviados como solicitados.

## Diagnóstico

`CLIMATE_COMFORT_DIAG` registra somente quando o snapshot tipado muda: ar,
temperaturas desejadas, ventilação, modo, operate_mode, recirculação,
desembacador, volante e retrovisores.

O diagnóstico não recebe `status.raw`, portanto não pode despejar VIN,
localização, token, certificado ou outros dados brutos.

## Preservado

- `config.yaml` fica em 1.12.102 até a CI publicar/promover 1.12.103;
- nenhum novo retry ou resend de conforto;
- janelas 1.12.102 preservadas;
- cortina e OCPP preservados.
