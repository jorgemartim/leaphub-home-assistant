# Leap Hub Gateway 1.12.50 — armazenamento WAL, coleta paralela e entrega dedicada

## Armazenamento

- A fila de telemetria passa a usar WAL com `synchronous=NORMAL`. Antes, `journal_mode=DELETE` com `synchronous=FULL` criava e apagava um journal a cada escrita, com vários `fsync`, e leitura bloqueava escrita. Em disco mecânico isso custava dezenas de milissegundos por transação e fazia o `/health` local passar de 3s, derrubando o watchdog do supervisor e provocando o corte das requisições vindas do site.
- **WAL é permitido, nunca imposto.** Se o volume não aceitar o arquivo `-shm`, o PRAGMA devolve o modo anterior, o motivo é registrado no log e o caminho DELETE continua valendo integralmente, sem intervenção. Foi essa ausência de saída que motivou o veto anterior a WAL; `validate_repository.py` passa a exigir o fallback em vez de proibir a string.
- `apparmor.txt` concede mapeamento de memória em `/data`, para que o perfil não seja o fator limitante. A fila continua restrita a `/data`.
- Uma conexão SQLite por thread substitui a reconexão por consulta. Antes, cada uma das 33 chamadas ao banco reabria o arquivo e reexecutava três PRAGMAs.
- A revalidação de permissões do diretório passa de "antes de cada consulta" para uma vez por minuto. O probe explícito de boot e de diagnóstico de falha não muda.
- A manutenção da fila passa de cada volta do laço (até duas vezes por segundo) para uma vez por minuto. A retenção continua diária.

## Coleta e entrega

- A coleta deixa de ser serializada em uma única thread. Contas diferentes são consultadas em paralelo, com o novo `telemetry_poll_workers`. O teto real de chamadas simultâneas à nuvem continua sendo `connector_max_parallel`, e a mesma conta continua serializada pela trava por conta e pela trava de sessão.
- A entrega ao site ganha thread própria. Antes ela morava no laço principal e uma lentidão da hospedagem parava a coleta de todos os veículos pelo tempo do timeout.
- O timeout de entrega passa de 45s para 25s, para desistir antes de o PHP da hospedagem ser encerrado por `max_execution_time`.
- O backoff de entrega passa de até 1800s para até 120s. O teto anterior deixava a telemetria de um usuário muda por meia hora após duas lentidões do site. A fila é persistente e o `event_id` é idempotente; repetir antes não duplica nada e não custa chamada à nuvem Leapmotor.

## Diagnóstico

- O resultado de comando remoto passa a expor `session_wait_ms`, `session_login_ms` e `unaccounted_ms`. Antes, a espera pela trava de sessão e a autenticação feitas no motor de telemetria não tinham contador: ficavam dentro de `remote_execute_ms` sem aparecer em nenhuma fase, e `session_prepare_ms` media apenas o `open_client()` do conector, que é próximo de zero quando o cliente é emprestado.
- A linha de log do worker passa a fechar a soma das fases com o tempo total.
- A versão da biblioteca `leapmotor-api` é resolvida uma vez por processo em vez de a cada `/health/details` e a cada payload de telemetria.

## Padrões

- `connector_max_parallel` passa de 2 para 4 e `telemetry_batch_size` de 25 para 5. **Instalações existentes mantêm os valores já salvos**; ajuste na aba Configuração do add-on.
- Novo `telemetry_poll_workers`, padrão 3, faixa de 1 a 6.

## Sem alteração

- Nenhuma migration, schema, credencial, vínculo conta-veículo, Charge ID, transação, configuração OCPP ou intervalo de telemetria veicular foi alterado.
- Nenhum comando físico é repetido. O contrato de `confirmation_pending` de 1.12.49 permanece intacto; ele apenas passa a ser reconciliado em segundos em vez de minutos.
