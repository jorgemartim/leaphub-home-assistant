# Leap Hub Gateway 1.12.79 — clima C10 por estado real

Base de revisão: Gateway 1.12.78 do `main`, com `connector.py` Git blob `175d86b42054adebc1f9466372126c3991fda8d4`.

## Alteração de clima

- `climate_off` passa a usar `ac_switch` diretamente.
- OFF do C10/B10/B05 passa a enviar somente `{"operate":"off"}`.
- `climate_on` passa a enviar o payload AUTO completo (`operate=auto`, `mode=nohotcold`) com setpoint recebido do site ou 24 °C como fallback.
- A confirmação deixa de usar apenas `ac_switch=true/false` e passa a distinguir `off`, `auto`, `cooling` e `heating`.
- `climate_mode` tem prioridade sobre `rapid_cooling` / `rapid_heating`.
- Os flags rápidos só entram como fallback quando exatamente um deles está ativo.
- A segunda tentativa protegida repete exatamente o mesmo comando de estado; não existe alternância de perfil.
- Continua existindo teto de duas transmissões; não há terceira tentativa nem aumento de polling.

## Versão

O patch também atualiza os marcadores internos que identificam a versão do add-on para 1.12.79 e o `RELEASE_TARGET`.

## Escopo

Nenhuma alteração funcional de OCPP, RFID, fila, banco, telemetria ou comandos de movimentação do veículo foi incluída. Os únicos arquivos fora do conector alterados no patch são marcadores de versão.
