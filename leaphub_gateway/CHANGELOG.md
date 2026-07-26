## 1.12.32

- Publicação pré-compilada do Home Assistant endurecida: o workflow só fica verde quando a tag exata do GHCR também puder ser consultada sem autenticação pelo Supervisor.
- Bootstrap do GitHub preparado para repositórios antigos: o pacote de recuperação traz todos os módulos atuais antes de anunciar a nova versão.
- O release exibido pelo Home Assistant continua contendo somente as informações da versão atual.
- Buildx mantém cache por arquitetura e faz smoke test da imagem exata antes da liberação.
- Sem alteração funcional em Connector Leapmotor, telemetria, OCPP, Wallbox, comandos remotos ou transporte de eventos.
