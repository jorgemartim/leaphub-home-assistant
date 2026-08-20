## 1.12.118

A distribuição continua pré-compilada no GHCR oficial e mantém a publicação em duas fases.

- atualiza `cryptography` para `50.0.0` e `Pillow` para `12.3.0`;
- fixa as duas dependências para builds reproduzíveis;
- preserva o uso atual de Fernet e as operações de imagem do C10;
- conexões SQLite de OCPP, diário de comandos, nonce e leitura de status agora
  fecham deterministicamente depois do commit ou rollback;
- corrige o teste OCPP que dependia da ordem de coleta e de variável de ambiente
  vazada por outro contrato;
- nenhum banco operacional, fila, evento, comando ou dado coletado é migrado,
  removido ou recalculado;
- comandos físicos, Trips, telemetria, proximidade e cadências permanecem
  inalterados;
- `config.yaml` permanece em `1.12.117` até o CI construir, testar, executar o
  smoke test e confirmar acesso anônimo à imagem GHCR `1.12.118`.
