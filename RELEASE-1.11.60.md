# Leap Hub Gateway 1.11.60

## Estado visual versão 4

- Diagnóstico por grupo de sensores com cobertura de portas, vidros, teto, luzes, segurança, clima, espelhos e carregamento.
- Fingerprint visual estável: o horário da coleta não força troca da imagem quando o estado não mudou.
- Fingerprint de amostra separada para auditoria de atualização.

## Fila ordenada e deduplicada

- Sequência monotônica por veículo.
- Uma leitura mais nova não ultrapassa evento anterior que ainda esteja aguardando reenvio.
- Leituras semanticamente iguais são suprimidas entre heartbeats, reduzindo uso de API, armazenamento e tráfego.
- Mudanças reais continuam entrando imediatamente na fila.

## Continuidade

- A fila permanece criptografada e persistente.
- Quando o Home Assistant está offline, o Leap Hub mantém a última leitura conhecida marcada como desatualizada.
- Nenhum estado é preenchido ou reconstruído artificialmente.
