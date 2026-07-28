# Upload 1.12.51

Calculado contra o estado atual da sua `main` (`c5be227`, "UPLOAD-1.12.50-merge"). Copie os 46
arquivos por cima e faça um commit.

## Opcional: dois arquivos renomeados

`tests/test_storage_throughput_1_12_50.py` e `tests/test_gateway_owned_fast_confirmation_1_12_50.py`
viraram `_1_12_51`. Pode apagar os antigos — mas **se esquecer, nada quebra**: eu testei com os dois
presentes e a suíte passa com 87 testes em vez de 76, só rodando os mesmos casos duas vezes.

## O que reprovou a 1.12.50

O validador passou. O build morreu no autoteste do `Dockerfile`:

```
assert journal == 'delete', journal
AssertionError: wal
```

A trava era do tipo certo — garantir que a fila abre e grava — com o alvo errado: um journal fixo.
Assim que o volume da imagem aceitou WAL, ela reprovou.

## Correções

- O autoteste da imagem valida o **contrato**, não o modo: aceita `wal` ou `delete`, exige que
  `storage_journal_mode` e `storage_status()['journal_mode']` reportem o mesmo modo que ficou
  valendo, e confirma que a fila responde a uma leitura real.
- O autoteste fecha a conexão de sondagem. `sqlite3.connect` como context manager encerra a
  **transação**, não a conexão — o arquivo da fila ficava aberto até o processo sair. No Linux isso
  passa despercebido; em qualquer plataforma é um handle vazando dentro do build.

## Melhorias desta versão

**Entrega com conexão TLS reaproveitada.** Cada lote abria uma conexão nova para o site. Depois que
o lote caiu para 5 eventos — necessário para caber no `max_execution_time` do PHP na hospedagem
compartilhada — o número de handshakes multiplicou. De uma conexão residencial, o handshake passou a
custar mais que a própria entrega. A conexão agora persiste entre lotes e é descartada em qualquer
erro de transporte, para que nenhuma resposta seja lida fora de ordem.

**`/health/details` responde sozinho a "está saturado?"**. Bloco novo `collection`:

```json
"collection": {
  "poll_workers": 3,
  "polls_in_flight": 1,
  "workers_saturated": false,
  "delivery_connection_reused": true,
  "journal_mode": "wal"
}
```

Diagnosticar a lentidão anterior exigiu ler o log linha a linha. Estes cinco campos respondem de
imediato se as coletas estão enfileiradas atrás dos workers e qual journal ficou valendo.

## Verificação já feita

Baixei o `c5be227`, apliquei este pacote por cima e rodei o validador completo:

```
76 passed        (tests/)
5 passed         (leaphub_gateway/tests/)
Repositório válido. Gateway alvo 1.12.51; App 1.12.48 (staged; imagem ainda não anunciada).
```

E, o que faltou da última vez, **extraí o autoteste do `Dockerfile` e executei contra os fontes
aplicados**, no mesmo layout de módulos que a imagem usa (`leaphub_*` no `site-packages`):

```
Autoteste de importação de Connector e telemetria concluído com sucesso.
```

O journal obtido nesse ambiente foi `wal`, e o motor reportou `wal` — exatamente o caso que reprovou
a 1.12.50.

## Depois de instalar

Instalações existentes mantêm as opções já salvas. Na aba Configuração:

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

Depois, em `/health/details`, confira `collection.delivery_connection_reused: true` após a segunda
entrega — é a prova de que o keep-alive está valendo.

`WAL indisponível neste volume` não é erro: é o fallback funcionando.
