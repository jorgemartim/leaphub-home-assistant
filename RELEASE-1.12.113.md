# Leap Hub Gateway 1.12.113 — fence mecânico + confirmação terminal

## Evidência de campo
Na 1.12.112, `windows_open` foi aceito/despachado em ~0,6s e abriu fisicamente,
mas a confirmação não chegou. Aproximadamente 5s depois `sunshade_open` também
foi despachado, porém o usuário não observou movimento da cortina. A imagem das
janelas também não mudou porque nenhuma leitura nova confirmou o estado aberto.

## Causa tratada
Janelas/cortina estavam no ACK-first e, por isso, o Gateway substituía o polling
`remoteCtlId` da leapmotor-api por retorno imediato. Isso liberava a lane da conta
antes de a operação mecânica anterior ter resultado remoto terminal.

## Correção
- `windows_open/close` e `sunshade_open/close` saem de ACK_FIRST_COMMANDS;
- o worker continua assíncrono para o navegador, mas mantém a serialização da
  conta até a biblioteca concluir/prescrever o remoteCtlId;
- timeout de result/query não autoriza reenvio: o classificador existente trata
  como ação aceita e delega o estado físico à telemetria FAST;
- confirmação esgotada vira `final_outcome=unconfirmed`, nunca `not_applied`;
- fallback local em 210s impede spinner eterno se o push ao site falhar;
- imagem continua estritamente derivada da telemetria real.

## Congelado
Payloads físicos, escala C10 0-10, defrost 2/0, Prepare, 40+12 comandos,
SAFE retry somente climate_on/off, auth/cooldown, OCPP, maintenance 1.12.112,
SQLite writer, 5/5/8 e 8/15/25/40/60/90.
