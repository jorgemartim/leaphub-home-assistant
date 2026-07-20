# Leap Hub Gateway 1.12.05

- Corrige a tempestade de consultas de status observada após comandos remotos.
- O status do comando informa uma cadência segura de nova consulta e deixa de poluir o log em nível INFO.
- A telemetria pós-comando passa de até oito leituras agressivas para no máximo três leituras espaçadas.
- O desligamento do clima usa o perfil informado pelo Leap Hub e não faz uma leitura extra antes do envio.
- O Gateway não repete automaticamente o comando quando o Leap Hub delega a confirmação à telemetria contínua.
- Mantém fila, idempotência, OCPP e promoção Beta/Produção inalterados.
