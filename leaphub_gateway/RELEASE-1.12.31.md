# Leap Hub Gateway 1.12.31

## Esta atualização

- O Home Assistant passa a usar a imagem pré-compilada `ghcr.io/jorgemartim/leaphub-gateway:1.12.31` em vez de recompilar o Gateway localmente.
- Atualizações normais passam a baixar apenas as camadas novas do container; dependências Python e sistema ficam nas camadas reutilizáveis da imagem.
- O release exibido pelo Home Assistant contém somente as informações desta versão.
- O workflow do GitHub valida, testa, usa cache Buildx, publica a imagem versionada e confirma que ela pode ser consultada sem autenticação antes do uso no Home Assistant.
- O Dockerfile continua no repositório para desenvolvimento/recuperação controlada, mas não é o caminho normal de instalação.

## Sem alteração funcional

Não altera comandos Leapmotor, OCPP, Wallbox, telemetria, MQTT experimental, filas, credenciais ou banco de dados.
