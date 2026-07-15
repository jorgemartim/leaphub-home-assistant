# Leap Hub Gateway

App unificado para Home Assistant OS que reúne Connector Leapmotor, OCPP Beta, OCPP Produção, Cloudflare Tunnel e painel de diagnóstico via Ingress.

A instalação pelo repositório oficial baixa uma imagem pronta do GitHub Container Registry. Não há compilação local no Home Assistant.

Leia a aba **Documentação** antes de migrar os Apps antigos. O Tunnel vem desativado por padrão para permitir a troca segura das rotas.


## Telemetria contínua 1.11.61

O Gateway mantém a fila criptografada, a sequência por veículo e a deduplicação da 1.11.60. A versão 1.11.61 publica o estado visual versão 5 com pistas seguras de resolução do modelo e da cor, informa se a imagem oficial da nuvem estava disponível e identifica grupos de sensores incompletos sem tratar ausência como estado fechado. Esses dados não incluem VIN, credenciais, localização ou identificadores da conta.
