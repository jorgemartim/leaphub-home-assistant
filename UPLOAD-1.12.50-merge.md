# Upload 1.12.50 — merge das duas features

Este pacote **junta** a sua confirmação FAST no Gateway (commit `3f24423`) com o trabalho de
armazenamento, paralelismo e entrega. Nada da sua feature foi perdido.

## O que aconteceu

1. `3f24423` — você publicou o 1.12.50 com `_arm_command_confirmation()` e o `boost` idempotente.
2. `fb7c994` ("donwgrade") — os fontes voltaram para 1.12.49, **mas** o
   `tests/test_gateway_owned_fast_confirmation_1_12_50.py` ficou no repositório.
3. Meus pacotes seguintes foram montados em cima do 1.12.49, então sobrescreveram a implementação
   e deixaram o teste órfão. Foi ele que reprovou com `KeyError: 'confirmation_armed_by_gateway'`.

Este pacote foi montado a partir do **seu** `3f24423`, com os meus patches reaplicados por cima.

## Como aplicar

Os 26 arquivos foram calculados contra o estado atual da sua `main` (`1ac1485`). Copie todos por
cima e faça um único commit — não precisa reverter nada antes.

Vários arquivos em `tests/` aparecem na lista porque estão **voltando** para a sua versão do
`3f24423`, que meus pacotes anteriores tinham sobrescrito.

## Verificação já feita

Baixei o `1ac1485`, apliquei este pacote por cima e rodei o `validate_repository.py` completo:

```
72 passed        (tests/)
5 passed         (leaphub_gateway/tests/)
Repositório válido. Gateway alvo 1.12.50; App 1.12.48 (staged; imagem ainda não anunciada).
```

Os 11 testes das duas features de 1.12.50 — `test_gateway_owned_fast_confirmation_1_12_50.py` e
`test_storage_throughput_1_12_50.py` — passam juntos.

## Como as duas features convivem

Elas se somam no mesmo caminho e não competem:

| Sua | Minha |
|---|---|
| arma a confirmação FAST assim que o comando termina | destrava a telemetria que executa essa confirmação |
| `_arm_command_confirmation()` após `handle_command` | coleta paralela, entrega dedicada, WAL |

Em `execute_command` as duas coexistem em sequência: primeiro a instrumentação preenche
`session_wait_ms`/`session_login_ms` em `phase_latency_ms`, depois `_arm_command_confirmation()`
arma a janela FAST. Nenhuma toca no que a outra escreve.

## Um detalhe do merge

O `_maintenance()` ganhou throttle de 60s para a retenção da fila, mas a expiração de sessão foi
extraída para `_expire_idle_sessions()` e continua rodando em **todo** ciclo. Isso importa para a
sua feature: a sessão que acabou de executar o comando precisa continuar viva para a confirmação
FAST reutilizá-la, e é o `session_idle_seconds` — não o throttle — que decide isso.

## Depois de instalar

Instalações existentes mantêm as opções já salvas. Ajuste na aba Configuração:

| Opção | Valor | Motivo |
|---|---|---|
| `telemetry_batch_size` | `5` | lote grande estoura o `max_execution_time` do PHP na HostGator |
| `connector_max_parallel` | `4` | sem isso a coleta paralela não acha vaga e reagenda em 30s |
| `telemetry_poll_workers` | `3` | coletas simultâneas de contas diferentes |

## Como confirmar que pegou

```
Fila de telemetria em WAL; leituras deixam de bloquear a escrita.
Telemetria contínua iniciada com fila persistente em /data/telemetry/telemetry.sqlite; 3 coletas paralelas e entrega dedicada.
```

`WAL indisponível neste volume` não é erro: é o fallback funcionando, e os demais ganhos continuam.

No primeiro comando remoto a linha do worker passa a fechar a conta de tempo:

```
... espera_sessao=Xms, login=Yms, preparo_sessao=Zms, dispatch=Wms, verificacao=Vms, nao_atribuido=Nms, execução_remota=Tms ...
```
