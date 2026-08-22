# Gateway 1.12.129 — polling OCPP escalável

Um único ciclo consulta comandos de até 200 wallboxes por requisição, em vez de
manter um loop HTTP independente por conexão. O despacho físico continua por
wallbox, em ordem, com paralelismo global limitado a 16.

O Gateway mantém fallback para `fetch_commands` individual quando o Site ainda
não oferece `fetch_commands_batch`. Para evitar pressão durante essa janela,
instale primeiro o Site 1.12.417 e depois este Gateway.

Não há migration nem alteração no SQLite, nas filas, nas transações ou na
telemetria preservada.
