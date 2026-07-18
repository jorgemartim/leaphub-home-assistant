# Leap Hub Gateway 1.11.78

## Confirmação segura de comandos

- A leitura rápida não permanece fixa em 3 segundos por 90 segundos.
- A cadência agora progride em 3, 6, 10 e 15 segundos.
- A janela termina assim que travas, climatização, carga ou abertura confirmam o estado esperado.
- Existe limite de oito leituras por comando, configurável entre quatro e doze.
- Somente o veículo afetado é consultado durante a confirmação.
- Mensagens da conta não são buscadas nessa janela.

## Prioridade e autenticação

- Comandos, testes de conta e sincronizações manuais têm prioridade sobre o worker automático.
- A telemetria cede a conexão quando existe uma operação do usuário aguardando.
- Depois de um login manual, a sessão automática antiga é descartada de forma controlada para evitar conflito de token.
- O login do Leap Hub/PWA continua separado da autenticação da nuvem Leapmotor.

## Ordem de atualização

1. Atualize o Gateway para **1.11.78**.
2. Reinicie o App e confirme a versão no painel.
3. Atualize o Leap Hub Beta para **1.12.72**.
