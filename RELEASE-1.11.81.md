# Leap Hub Gateway 1.11.81

## Comandos instantâneos e protegidos

- O clique retorna ao Leap Hub imediatamente; a execução continua em uma fila prioritária no Gateway.
- A telemetria libera a conta antes do login necessário ao comando remoto.
- O mesmo `request_id` nunca executa a ação duas vezes.
- O estado do processamento pode ser consultado sem criar uma nova sessão Leapmotor.
- Falhas anteriores ao envio ficam registradas e aparecem na interface.
- Se a nuvem já tiver aceitado a ação e perder a confirmação, o comando permanece pendente e não é repetido.
- A barreira de estabilização continua ativa antes da retomada da telemetria.

## Ordem de atualização

1. Atualize o Gateway para **1.11.81**.
2. Reinicie o App e confirme a versão no painel.
3. Atualize o Leap Hub Beta para **1.12.75**.
