from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_PATH = ROOT / "leaphub_gateway" / "connector.py"
spec = importlib.util.spec_from_file_location("leaphub_gateway_sentry_evidence", CONNECTOR_PATH)
assert spec and spec.loader
connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector)

assert connector.CONNECTOR_VERSION == "1.12.60"

positive = connector.safe_remote_result_summary({"result": 0, "message": "ok", "remoteCtlId": "secret-id", "token": "must-not-leak"})
assert positive["result"] == 0
assert positive["message"] == "ok"
assert positive["remote_control_id_present"] is True
assert "token" not in positive
assert "secret-id" not in str(positive)
assert connector.remote_result_signal(positive) == "positive"

negative = connector.safe_remote_result_summary({"success": False, "reason": "rejected", "vin": "WLMSECRET"})
assert negative["success"] is False
assert connector.remote_result_signal(negative) == "negative"
assert "WLMSECRET" not in str(negative)

unknown = connector.safe_remote_result_summary({"foo": "bar"})
assert connector.remote_result_signal(unknown) == "unknown"

source = CONNECTOR_PATH.read_text(encoding="utf-8")
for token in ("remote_result_evidence", "remote_result_signal", "remote_result_summary"):
    assert token in source


server_source = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
for token in ("evidencia=%s", "sinal=%s", "resumo=%s", "remote_result_summary"):
    assert token in server_source

print({"ok": True, "checks": 16, "version": "1.12.60"})
