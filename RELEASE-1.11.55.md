# Leap Hub Gateway 1.11.55

## Destaques

- Telemetria contínua com consulta adaptativa em viagem, recarga, estacionamento e repouso.
- Fila SQLite persistente, criptografada e idempotente.
- Reenvio automático quando o site ou a internet retornam.
- Entrega ao ABRP somente de leituras recentes processadas pelo Leap Hub.
- Healthcheck interno em cache e logs locais menos poluídos.
- Configuração pronta para Beta; Produção permanece desativada por padrão.

## Limite real

Quando o Home Assistant inteiro está desligado, não há coleta naquele intervalo. O Leap Hub não inventa posições, horários ou consumo e marca a lacuna para posterior reconciliação com dados reais disponíveis.
