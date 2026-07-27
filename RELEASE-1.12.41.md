# Leap Hub Gateway 1.12.41

Atualização conservadora sobre a 1.12.40.

## OCPP

- Falhas temporárias continuam na fila persistente com retry/backoff.
- Rejeições permanentes da API interna não entram em retry infinito.
- A entrega rejeitada é registrada em quarentena sanitizada no SQLite local do Gateway.
- A quarentena armazena hashes e metadados mínimos; não armazena payload OCPP bruto, segredo nem Charge ID em texto claro.
- FIFO por Charge ID permanece preservado.

## Compatibilidade

- Nenhuma opção existente é removida ou renomeada.
- Nenhum segredo, vínculo, veículo, wallbox ou Charge ID é recriado.
- O arquivo SQLite existente é atualizado de forma aditiva com `CREATE TABLE IF NOT EXISTS`; filas existentes são mantidas.
- Connector e telemetria mantêm o comportamento da 1.12.40.

Atualize o Gateway 1.12.40 para 1.12.41 e aguarde o App reiniciar por completo antes de instalar a Beta 1.12.241.
