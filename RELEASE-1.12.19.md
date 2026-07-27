# Leap Hub Gateway 1.12.19

## Monitoramento contínuo em segundo plano

- Assinaturas habilitadas continuam sendo consultadas depois que a janela de presença do site expira.
- Abrir o Leap Hub apenas ativa a cadência rápida; fechar a tela retorna ao perfil econômico.
- O intervalo máximo em repouso é de 300 segundos por padrão.
- Viagens, recargas e alterações continuam entrando na fila persistente e são entregues ao site sem depender da interface.
- Sessão única por conta, cooldown, idempotência de comandos, OCPP e fila SQLite foram preservados.

