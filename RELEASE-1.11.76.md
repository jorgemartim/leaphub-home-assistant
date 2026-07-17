# Leap Hub Gateway 1.11.76

## Correções

- Falhas temporárias da nuvem ao emitir certificado não são mais tratadas como senha incorreta.
- Uma sincronização manual validada pelo site consegue remover `auth_required` mesmo quando o usuário manteve a mesma senha.
- A assinatura de telemetria volta para a fila segura após a confirmação, sem sequência agressiva de logins.
- A imagem oficial não mantém o reflexo do vidro fechado na frente de uma porta aberta.

## Ordem de atualização

1. Atualize o App **Leap Hub Gateway** no Home Assistant para 1.11.76.
2. Atualize o Leap Hub Beta para 1.12.46.
3. Na conexão afetada, use **Tentar corrigir automaticamente** uma única vez.
