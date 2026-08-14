# Leap Hub Gateway 1.12.91 — comando manual sem trava global no precheck

Base publicada obrigatória: **1.12.90** (`8c1d09285d65aee1c4c76d5b11324768d5f4b7b4`).

## Problema comprovado

No teste de campo da 1.12.90, um `quick_heat` teve `latência_conta=1ms` e `dispatch=612ms`, mas ficou **12.292ms** em `trava_motor`; o total foi 12.918ms. Duas tentativas anteriores atingiram o teto de 20s e não enviaram o comando ao veículo.

## Correção

O `SELECT subscription_id,cooldown_until,status` do precheck é somente-leitura. A 1.12.91 deixa de adquirir `self.lock` nessa leitura e usa a conexão SQLite por thread com teto de **0,75s**. Em `locked/busy`, a falha continua temporária e ocorre antes de qualquer dispatch.

`engine_lock_wait_ms` continua presente e passa a ser zero, preservando métricas e formato de log.

## Guardrails preservados

- trava por conta e `_session_operation_lock`;
- mesmo `LeapmotorApiClient`, sem uso concorrente;
- nenhum segundo cliente;
- nenhum polling adicional;
- bounded reads 1.12.89;
- confirmação mode-aware 1.12.90;
- payload C10 e semântica AUTO/COOL/HEAT/OFF;
- `climate_off` com no máximo duas transmissões exatas;
- Site intacto.

`config.yaml` permanece 1.12.90 no commit funcional e só é promovido a 1.12.91 pelo GitHub Actions após validação, build, smoke test e publicação da imagem.
