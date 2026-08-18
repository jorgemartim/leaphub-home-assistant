# Leap Hub Gateway 1.12.111 — prioridade de comando sobre manutencao SQLite

## Evidencia de campo
Na Gateway 1.12.110 instalada, o novo diagnostico mostrou manutencao local em
39.531 ms e 42.338 ms. Durante a mesma janela, `/telemetry/subscriptions/boost`
respondeu 503 por `database is locked`, e `CONFIRM_SCHED_DIAG` cresceu de 5.335
ms ate 32.786 ms. O despacho fisico continuou separado: `quick_cool` armou FAST
em 5 ms e `climate_off` terminou o caminho remoto em ~2,6 s.

## Causa
A 1.12.110 removeu corretamente o convoy de `self.lock`, mas a manutencao passou
a concorrer em thread propria como escritora SQLite. A limpeza antiga fazia
UPDATE/DELETE sem lote sobre a fila inteira; em WAL leitores convivem, mas existe
apenas um escritor por vez. Assim a manutencao podia impedir boost, persistencia
de confirmacao e bookkeeping de autenticacao.

## Correcao restrita
- coordenador unico `sqlite_writer_lock` para writes internos do telemetry.sqlite;
- `_db` entrega proxy que serializa INSERT/UPDATE/DELETE/DDL e segura BEGIN ate COMMIT/ROLLBACK, sem serializar SELECT;
- folga inicial da manutencao: 180 s;
- intervalo de poda em disco: 60 s;
- busy timeout exclusivo da manutencao: 150 ms;
- lote maximo: 200 IDs por classe/passada;
- comando/confirmacao pendente => manutencao cede sem escrever;
- descoberta de IDs em SELECT; mutacao somente por PK em lote pequeno;
- remove o DELETE bulk terminal antigo;
- throttle somente apos passada concluida;
- nenhuma mudanca de payload, retry, matcher, OCPP ou cadencia.

## Congelado
SAFE retry somente climate_on/climate_off; janelas 0-100 -> 0-10; defrost
wshld=2/0; matchers de windows/sunshade; auth/cooldown; OCPP; 5/5/8 e
8/15/25/40/60/90. `config.yaml` so sobe no fluxo normal de publicacao.
