from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")

# 1.12.58 — o conjunto deixou de ser derivado de EXPERIMENTAL_COMMAND_METHODS ao
# entrar um segundo experimental (prepare_car): derivado, o comando novo herdaria a
# sonda e os campos de diagnóstico do Sentinela, que são só dele. O que o contrato
# precisa afirmar é o conteúdo, não de onde ele vem — e que não volte a ser derivado.
assert 'SENTRY_COMMANDS = frozenset({"sentry_on", "sentry_off"})' in CONNECTOR
assert 'SENTRY_COMMANDS = frozenset(EXPERIMENTAL_COMMAND_METHODS)' not in CONNECTOR
assert 'dispatch_ack = "not_dispatched"' in CONNECTOR
assert 'remote_result_status = "not_started"' in CONNECTOR
assert 'dispatch_ack = "library_returned"' in CONNECTOR
assert 'remote_result_status = "completed"' in CONNECTOR
assert 'dispatch_ack = "cloud_accepted_result_pending"' in CONNECTOR
assert '"sentry_probe": command in SENTRY_COMMANDS' in CONNECTOR
assert 'confirmation_reason == "result_timeout"' in CONNECTOR
assert 'resultado_remoto=%s' in SERVER
assert 'motivo=%s' in SERVER
print({"ok": True, "checks": 10, "version": "1.12.71"})
