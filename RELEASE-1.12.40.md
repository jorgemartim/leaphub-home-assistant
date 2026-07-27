# Leap Hub Gateway 1.12.40

## Resultado

- O snapshot FAST de confirmação chega ao Leap Hub mesmo quando o veículo já
  estava no estado solicitado.
- Um `unlock` redundante deixa de ficar indefinidamente em
  `confirmation_pending`.
- Mudanças posteriores, incluindo auto-lock, continuam sendo entregues como
  estado físico autoritativo.

## Segurança

- A exceção à deduplicação vale somente dentro da janela de confirmação.
- Nenhum comando aceito é repetido automaticamente.
- MQTT continua passivo; comandos permanecem no REST autenticado.
- Sem migration e sem alteração de credenciais.

## Instalação

Atualize o Gateway 1.12.39 para 1.12.40, reinicie e confirme a versão. Depois
instale o Leap Hub Beta 1.12.240 sobre a 1.12.239.

