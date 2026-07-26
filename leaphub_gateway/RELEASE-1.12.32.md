# Leap Hub Gateway 1.12.32

## Distribuição / Home Assistant

- Mantém `image: ghcr.io/jorgemartim/leaphub-gateway`, portanto o Home Assistant baixa a imagem pronta em vez de compilar o Gateway localmente.
- A publicação só é considerada pronta quando `ghcr.io/jorgemartim/leaphub-gateway:1.12.32` existe e pode ser consultada anonimamente.
- Na primeira publicação do pacote GHCR, se ele nascer privado, o workflow para com uma mensagem explícita. Depois de tornar o pacote público no GitHub, basta reexecutar o workflow; as próximas tags herdam a visibilidade do pacote.
- `CHANGELOG.md` contém somente o bloco da 1.12.32 para a tela de atualização do Home Assistant.

## Compatibilidade

- Nenhuma migration de configuração.
- Mantém as opções existentes e os serviços Connector Leapmotor, telemetria, OCPP, Cloudflare e Ingress.
- Sem mudança no transporte de comandos e sem ativação automática de MQTT.
