from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8")

checks = {
    "version": 'VERSION = "1.12.14"' in SERVER and 'version: "1.12.14"' in CONFIG,
    "api_contract": "API_VERSION = 2" in SERVER and 'X-LeapHub-API-Version' in SERVER,
    "trace": 'X-Request-ID' in SERVER and 'trace_id' in SERVER,
    "compatibility": 'incompatible_api' in SERVER,
    "health": 'capability_schema_version' in SERVER,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("contract smoke failed: " + ", ".join(failed))
print({"ok": True, "checks": len(checks)})
