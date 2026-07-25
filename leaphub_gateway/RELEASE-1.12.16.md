# Leap Hub Gateway 1.12.16

- Reutiliza conexões HTTP(S) entre o OCPP Gateway e o Leap Hub, reduzindo DNS, TCP e TLS repetidos.
- Diferencia indisponibilidade temporária de credencial recusada durante a resolução Beta/Produção.
- Permite reconexão da mesma wallbox mesmo quando o limite de conexões está ocupado.
- Consolida Heartbeats pendentes durante indisponibilidade para evitar crescimento sem utilidade da fila.
- Tenta um único refresh de sessão também quando a leitura de mensagens detecta expiração.
- Reduz a permanência em consulta de estacionado antes do intervalo de repouso, sem alterar a confirmação de estados.
- Mantém build local do Home Assistant, API v2, OCPP 1.6, 25 comandos, SQLite e configurações existentes.
