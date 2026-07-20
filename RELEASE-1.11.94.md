# Leap Hub Gateway 1.11.94

- Implementa climatização em duas etapas: despertar/aguardar veículo disponível e só então aplicar o HVAC.
- O primeiro aceite da nuvem não é mais confundido com climatização fisicamente ligada.
- Corrige o fluxo de timeout de resultado para não cair no tratamento de erro depois que a escrita já foi aceita.
- Faz no máximo uma segunda entrega de `climate_on`/`climate_off`, somente por serem comandos de estado idempotentes.
- Antes da repetição, consulta uma leitura nova para evitar duplicidade desnecessária.
- Mantém trava, destrava, porta-malas e demais ações sem repetição automática.
- Estados `vehicle_waking`, `vehicle_awake`, `climate_dispatching`, `climate_verifying` e `retry_wait` permanecem ativos até o worker realmente terminar.
- `sent` passa a ser gravado somente por `command_journal_finish`, após o retorno completo do processamento.
- Nenhum token, PIN, senha ou VIN é registrado.
