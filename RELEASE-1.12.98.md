# Leap Hub Gateway 1.12.98 — Official diário + confirmação da posição da cortina

Base obrigatória: `ec7bf71c72e67154f4dd04fe52ecad766c7027b7` (1.12.97 publicada e homologada em campo).

## Escopo funcional

1. **Cortina por porcentagem (`sunshade_position`)**
   - a transmissão física permanece exatamente a mesma da 1.12.97;
   - continua em uma única transmissão, sem retry físico e sem entrar em ACK-first;
   - após o retorno da biblioteca, o Gateway arma confirmação FAST e compara `sunshade_percent` com o degrau efetivo de 10%;
   - 45% continua sendo enviado como degrau 5 e confirmado somente em 50%; 48% não confirma 50%;
   - uma nova porcentagem supersede uma porcentagem anterior, mas o mesmo `request_id` permanece idempotente.

2. **Official `drivingRecord`**
   - a única sonda real do C10 em 1.12.97 comprovou totais + blocos diários;
   - somente os campos comprovados entram em allowlist;
   - unidades/escalas permanecem `unverified`: nenhum RAW vira km/kWh automaticamente;
   - corpo bruto, VIN, token, referências desconhecidas e chaves extras continuam redigidos;
   - uma única leitura, sem retry, sessão existente, baixa prioridade e prioridade absoluta a comando manual.

## Congelado

- `sunshade_open` / `sunshade_close` e sua estratégia ACK-first;
- `climate_off`, máximo de duas transmissões e demais comandos físicos;
- cadência pós-comando 5/5/8, janela e prioridade manual;
- imagem, OCPP, HMAC, sessão por conta e transporte;
- Site/Produção. O Site Beta 1.12.360 é publicado em pacote separado.
