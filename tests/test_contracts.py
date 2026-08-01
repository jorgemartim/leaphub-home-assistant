from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8")

checks = {
    # config.yaml so e promovido depois da validacao: o alvo e a versao ainda
    # publicada precisam passar, senao o proprio gate reprova o candidato.
    "version": 'VERSION = "1.12.67"' in SERVER and ('version: \"1.12.66\"' in CONFIG or 'version: \"1.12.67\"' in CONFIG),
    "api_contract": "API_VERSION = 2" in SERVER and 'X-LeapHub-API-Version' in SERVER,
    "trace": 'X-Request-ID' in SERVER and 'trace_id' in SERVER,
    "compatibility": 'incompatible_api' in SERVER,
    "health": 'capability_schema_version' in SERVER,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("contract smoke failed: " + ", ".join(failed))
print({"ok": True, "checks": len(checks)})
