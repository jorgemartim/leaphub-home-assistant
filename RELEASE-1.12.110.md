# Leap Hub Gateway 1.12.110 — isolamento do scheduler de confirmacao

## Evidencia de campo
O despacho de comandos continuou rapido (~0,6 s em climate/windows), mas o arme
FAST de `climate_on` ficou 17,887 s dentro de `boost()`. `windows_open` foi
despachado em ~0,6 s e ficou sem veredito terminal no recorte, enquanto a
cortina confirmou somente 48 s depois.

## Causa
`boost()`, o scheduler, a fila de eventos e a manutencao compartilhavam
`self.lock`. A fila ainda usa `BEGIN IMMEDIATE`; portanto uma espera de SQLite
podia virar um convoy global e parar agenda/confirmacao mesmo depois de o carro
ja ter recebido o comando.

## Correcao
- `schedule_lock` exclusivo para coordenacao de agenda/confirmacao;
- `boost`, post-poll, reschedule e auth_required deixam de depender do lock global;
- scheduler read-only usa snapshot SQLite/WAL com teto curto;
- fila preserva BEGIN/COMMIT/ROLLBACK sem reter o lock global;
- manutencao roda em worker dedicado e com espera SQLite limitada;
- diagnosticos de atraso do scheduler/manutencao.

## Congelado
Payloads fisicos; SAFE retry somente climate_on/off; janelas 0-100 -> 0-10;
matchers de windows/sunshade; defrost wshld=2/0; OCPP; auth/cooldown; cadencia
5/5/8 e backoff 8/15/25/40/60/90. `config.yaml` nao e promovido pelo patch.
