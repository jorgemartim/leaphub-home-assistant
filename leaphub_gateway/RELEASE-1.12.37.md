# Leap Hub Gateway 1.12.37

Correção de recuperação pré-envio para sessões Leapmotor expiradas.

Quando a biblioteca informa `remote verify failed: Token is invalid` e deixa explícito que a verificação foi rejeitada antes da ação física, o Gateway fecha a sessão compartilhada e tenta uma única autenticação limpa. Erros de token durante a consulta do resultado remoto continuam sendo tratados como estado ambíguo pós-aceite e nunca provocam reenvio automático do comando.

O pipeline GHCR, OCPP, Event Transport e a política de prioridade manual permanecem inalterados.
