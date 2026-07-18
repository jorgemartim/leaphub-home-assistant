# Leap Hub Gateway 1.11.80

## Conexão e comandos remotos

- Comandos aceitos pela nuvem não são marcados como falha quando apenas a consulta do resultado perde o token.
- A telemetria aguarda 12 segundos após uma operação remota antes de criar nova sessão.
- Uma leitura automática em andamento cede a conta em pontos seguros para o comando do usuário.
- A primeira reconexão após um comando usa espera moderada e sessão limpa.
- VIN, token e senha criptográfica de operação não aparecem mais nos logs.
- Logs antigos do Gateway são higienizados na primeira inicialização desta versão.
- Comandos recebem um identificador persistente para não serem executados novamente caso a resposta HTTP se perca.

## Ordem de atualização

1. Atualize o App Leap Hub Gateway para **1.11.80**.
2. Reinicie o App.
3. Atualize o Leap Hub Beta para **1.12.74**.
4. Teste um comando e aguarde a confirmação automática do estado.
