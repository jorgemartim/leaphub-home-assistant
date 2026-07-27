## 1.12.45

- Distribuição pré-compilada via GHCR preservada.
- OCPP SQLite single-writer coordination to eliminate cross-wallbox write contention.
- Reconnect route/owner write coalescing and aggregate reconnect-storm diagnostics.
- Async vehicle sync with short-lived HTTP polling instead of a long Cloudflare request.
- Health diagnostics now include latency and consecutive failures.
- No destructive migration; existing queues and state are preserved.
