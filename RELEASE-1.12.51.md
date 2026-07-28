# Leap Hub Gateway 1.12.51 — build destravado e entrega com conexão reaproveitada

## Por que esta versão existe

A 1.12.50 passou no validador e reprovou no build da imagem: o autoteste do `Dockerfile`
exigia `journal_mode == 'delete'`, e o volume da imagem aceitou WAL. A trava era do tipo certo
(garantir que a fila abre e grava) com o alvo errado (um journal fixo).

## Correções

- O autoteste da imagem passa a validar o **contrato**, não um modo: aceita `wal` ou `delete`,
  exige que `storage_journal_mode` e `storage_status()['journal_mode']` reportem o mesmo modo que
  ficou valendo, e confirma que a fila responde a uma leitura real.
- O autoteste fecha a conexão de sondagem. `sqlite3.connect` como context manager encerra a
  transação, não a conexão.

## Melhorias

- **Entrega com conexão reaproveitada.** Cada lote abria uma conexão TLS nova para o site. Com o
  lote reduzido para caber no `max_execution_time` da hospedagem compartilhada, o número de
  handshakes multiplicou, e de uma conexão residencial o handshake passou a custar mais que a
  entrega em si. A conexão agora é mantida entre lotes e descartada em qualquer erro de transporte.
- **`/health/details` responde sozinho a "está saturado?"**. O novo bloco `collection` traz
  `poll_workers`, `polls_in_flight`, `workers_saturated`, `delivery_connection_reused` e
  `journal_mode`.

## Compatibilidade

Nada de comando físico, credencial, vínculo, OCPP, MQTT, schema ou migration foi alterado.
A confirmação FAST do Gateway e todo o trabalho de armazenamento e paralelismo da 1.12.50
permanecem intactos.
