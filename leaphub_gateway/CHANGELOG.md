## 1.12.129

- troca o polling HTTP por wallbox por lotes de até 200 identidades;
- limita a 16 execuções físicas paralelas e mantém ordem por equipamento;
- com 500 wallboxes ociosas, reduz o polling de cerca de 50 requests/s para
  aproximadamente 0,3 request/s;
- preserva fallback individual durante atualização Site/Gateway e não altera
  SQLite, filas, transações ou telemetria.
- mantém a distribuição pré-compilada no GHCR e a promoção segura em duas fases.
