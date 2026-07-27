## 1.12.41

- Classifica rejeições permanentes da API OCPP separadamente de falhas temporárias.
- Mantém retry com backoff para timeout, 408, 425, 429 e 5xx.
- Eventos permanentemente rejeitados deixam a fila ativa e entram em quarentena sanitizada, sem payload bruto, segredo ou Charge ID em texto claro.
- Preserva FIFO por Charge ID e libera a sequência somente após entrega ou quarentena segura do evento bloqueador.
- Expõe contadores de quarentena nos diagnósticos do Gateway.
- Mantém Connector, telemetria, MQTT passivo, sessão, comandos e configurações existentes sem reset.
- A distribuição continua usando a imagem GHCR oficial pré-compilada, sem alterar a instalação existente.
