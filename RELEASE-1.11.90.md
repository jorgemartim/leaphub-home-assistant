# Leap Hub Gateway 1.11.90

- Corrige o erro `Leapmotor cert sync failed: Token is invalid` observado no comando de climatização.
- A recuperação só é aplicada ao estágio de certificado, que acontece antes da ação ser enviada ao veículo.
- Fecha a sessão expirada, autentica novamente uma única vez e executa o comando original.
- Nunca usa essa repetição para erros ambíguos posteriores ao envio.
- Mantém trava por conta, prioridade de comando e proteção contra duplicidade.
