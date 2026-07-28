# Upload 1.12.50

Envie **todos** os arquivos listados em `CHANGED-FILES-1.12.50.txt` para a `main`. São 14, e alguns
existem só para satisfazer o `validate_repository.py` — se faltar qualquer um, o job
`Validate staged repository` falha antes de compilar.

| Arquivo | Por que está aqui |
|---|---|
| `leaphub_gateway/ocpp_gateway.py` | só a constante `GATEWAY_VERSION`; o validador exige a versão-alvo em todos os módulos |
| `leaphub_gateway/privacy.py` | idem, `PRIVACY_VERSION` |
| `leaphub_gateway/CHANGELOG.md` | o validador exige **apenas** o heading da versão-alvo |
| `leaphub_gateway/config.yaml` | nova opção `telemetry_poll_workers` no schema e padrões novos |
| `leaphub_gateway/apparmor.txt` | mapeamento de memória em `/data`, para o WAL |
| `.github/scripts/validate_repository.py` | a regra de WAL passa a exigir o fallback em vez de proibir |

O campo `version:` do `config.yaml` continua anunciando 1.12.48; `leaphub_gateway/RELEASE_TARGET`
aponta para 1.12.50. O workflow promove a versão somente depois de build, testes, smoke test e
acesso público à imagem GHCR.

## Sobre a mudança na regra de WAL

O validador tinha `if "PRAGMA journal_mode=WAL" in telemetry_source: fail(...)`, com a mensagem
"voltou a forçar WAL". A palavra-chave é **forçar**: o risco era o motor exigir WAL sem saída e
deixar a fila inacessível num `/data` que recusasse o arquivo `-shm`.

A regra nova mantém a proteção e troca o alvo: WAL é aceito, mas só se o código provar que tem
fallback. O validador passa a exigir quatro marcadores no `telemetry_engine.py` — o
`except sqlite3.OperationalError`, o log `WAL indisponível neste volume`, a marcação
`storage_journal_mode = "wal"` e o `synchronous=NORMAL`. O caminho DELETE continua obrigatório e
intacto. Na prática: o journal deixa de ser imposição do código e passa a ser escolha do volume.

Se preferir não mexer no validador agora, remova as duas linhas `db.execute("PRAGMA journal_mode=WAL")`
e o bloco `if current == "wal":` do `_configure_journal`. O add-on volta a DELETE + `synchronous=FULL`
e todo o resto da release continua valendo — você perde o ganho de `fsync`, mas mantém a conexão
persistente, a manutenção com throttle, o paralelismo, a entrega dedicada e o backoff curto.

## Antes de publicar

```bash
python -m pytest tests/ -q
```

O validador do workflow roda `pytest -q tests` e `pytest -q leaphub_gateway/tests`, além de
`py_compile` nos seis módulos. O teste novo é `tests/test_storage_throughput_1_12_50.py`.

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

Se aparecer `WAL indisponível neste volume`, o fallback entrou em ação: o comportamento anterior foi
preservado e os demais ganhos continuam valendo. Não é erro, é o contrato funcionando.

No primeiro comando remoto, a linha do worker passa a fechar a conta:

```
... espera_sessao=Xms, login=Yms, preparo_sessao=Zms, dispatch=Wms, verificacao=Vms, nao_atribuido=Nms, execução_remota=Tms ...
```

`nao_atribuido` próximo de zero significa que a instrumentação cobre todo o tempo do comando. Se
continuar alto, sobrou fase sem medir e vale investigar antes de seguir.

## Reversão

Restaure os arquivos da 1.12.49 e reinicie o add-on. A fila em WAL continua legível por qualquer
versão do SQLite usada pelo projeto; para voltar o journal ao modo antigo, com o add-on parado:

```bash
sqlite3 /data/telemetry/telemetry.sqlite "PRAGMA wal_checkpoint(TRUNCATE); PRAGMA journal_mode=DELETE;"
```

Nenhum dado é perdido em nenhuma das direções.
