# Leap Hub Gateway

App unificado para Home Assistant OS que reúne Connector Leapmotor, OCPP Beta, OCPP Produção, Cloudflare Tunnel e painel de diagnóstico via Ingress.

A instalação pelo repositório oficial baixa uma imagem pronta do GitHub Container Registry. Não há compilação local no Home Assistant.

Leia a aba **Documentação** antes de migrar os Apps antigos. O Tunnel vem desativado por padrão para permitir a troca segura das rotas.


## Telemetria contínua 1.11.60

O Gateway guarda credenciais e eventos criptografados em `/data/telemetry`, usa intervalos adaptativos e reenvia a fila quando o site volta. A versão 1.11.60 mantém uma sequência por veículo, entrega cada leitura na ordem correta e suprime amostras semanticamente idênticas entre heartbeats. Mudanças reais continuam sendo enviadas imediatamente. Uma queda do Home Assistant inteiro cria uma lacuna real; o sistema mantém a última leitura conhecida no site, marcada como desatualizada, sem inventar rota, consumo ou posições.
