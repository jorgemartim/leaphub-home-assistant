## 1.12.50

Distribuição pré-compilada preservada, com publicação em duas fases.

- Arma a confirmação FAST dentro do Gateway assim que o comando remoto termina, sem depender do próximo ciclo do Worker PHP.
- Reutiliza a sessão que acabou de executar o comando e direciona a coleta ao `remote_id` correto do veículo.
- Torna o `boost` do mesmo `request_id` idempotente: amostras e horário inicial não voltam a zero.
- Preserva o contexto de confirmação durante estados temporários de recuperação.
- Não repete comandos físicos, não altera credenciais, OCPP, MQTT, schema ou dados existentes.
