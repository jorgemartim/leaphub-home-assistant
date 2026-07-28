# Upload 1.12.50

Envie somente os arquivos listados em `CHANGED-FILES-1.12.50.txt` para a `main`.

Diferente de 1.12.49, esta release **inclui `leaphub_gateway/config.yaml`**, porque adiciona a opção
`telemetry_poll_workers` ao schema do add-on e ajusta os padrões de `connector_max_parallel` e
`telemetry_batch_size`. O campo `version:` do `config.yaml` continua anunciando 1.12.48;
`leaphub_gateway/RELEASE_TARGET` aponta para 1.12.50. O workflow promove a versão somente depois de
build, testes, smoke test e acesso público à imagem GHCR.

## Antes de publicar

```bash
python -m pytest tests/ -q
```

Com atenção a `test_storage_throughput_1_12_50.py` (novo) e aos que cobrem áreas tocadas:

```bash
python -m pytest tests/test_storage_throughput_1_12_50.py \
                 tests/test_background_telemetry_1_12_19.py \
                 tests/test_connection_orchestrator_1_12_29.py \
                 tests/test_command_session_reuse_1_12_39.py \
                 tests/test_command_confirmation_delivery_1_12_40.py \
                 tests/test_verified_upsert_session_1_12_49.py \
                 tests/test_planned_restart_order_1_12_48.py -q
```

## Depois de instalar

Instalações existentes **mantêm os valores já salvos** das opções. Os padrões novos valem apenas
para instalação limpa. Ajuste na aba Configuração do add-on:

| Opção | Valor recomendado | Motivo |
|---|---|---|
| `telemetry_batch_size` | `5` | lote grande estoura o `max_execution_time` do PHP na hospedagem |
| `connector_max_parallel` | `4` | sem isso a coleta paralela não tem vaga e reagenda em 30s |
| `telemetry_poll_workers` | `3` | coletas simultâneas de contas diferentes |

## Como confirmar que pegou

No log do add-on, logo após o restart:

```
Fila de telemetria em WAL; leituras deixam de bloquear a escrita.
Telemetria contínua iniciada com fila persistente em /data/telemetry/telemetry.sqlite; 3 coletas paralelas e entrega dedicada.
```

Se aparecer `WAL indisponível neste volume`, o fallback entrou em ação e o comportamento anterior
foi preservado; os demais ganhos continuam valendo.

No primeiro comando remoto, a linha do worker passa a fechar a conta:

```
... espera_sessao=Xms, login=Yms, preparo_sessao=Zms, dispatch=Wms, verificacao=Vms, nao_atribuido=Nms, execução_remota=Tms ...
```

`nao_atribuido` próximo de zero significa que a instrumentação está cobrindo todo o tempo do comando.
Se ele continuar alto, sobrou fase sem medir e vale investigar antes de seguir.

## Reversão

Restaure os arquivos da 1.12.49 e reinicie o add-on. A fila em WAL continua legível por qualquer
versão do SQLite usada pelo projeto; se quiser voltar o journal ao modo antigo, com o add-on parado:

```bash
sqlite3 /data/telemetry/telemetry.sqlite "PRAGMA journal_mode=DELETE;"
```

Nenhum dado é perdido em nenhuma das direções.
