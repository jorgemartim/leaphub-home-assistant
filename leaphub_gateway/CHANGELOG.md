## 1.12.31

- Atualização rápida no Home Assistant por imagem GHCR pré-compilada; o Supervisor deixa de compilar Python e dependências localmente nas atualizações normais.
- `config.yaml` passa a apontar explicitamente para `ghcr.io/jorgemartim/leaphub-gateway`, com a tag controlada pela própria versão do App.
- Release enxuto: o Home Assistant exibe somente as mudanças da versão que está sendo instalada.
- Publicação no GitHub usa cache de camadas, smoke test da imagem exata e verificação de acesso anônimo ao manifesto antes de considerar a publicação pronta.
- Sem mudança funcional em Connector Leapmotor, telemetria, OCPP, Wallbox ou transporte de eventos.
