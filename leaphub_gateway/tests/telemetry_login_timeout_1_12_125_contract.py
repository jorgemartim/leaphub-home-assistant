from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "leaphub_gateway"
target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
connector = (APP / "connector.py").read_text(encoding="utf-8")
telemetry = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
config = (APP / "config.yaml").read_text(encoding="utf-8")

tree = ast.parse(connector)
create_client = next(
    node for node in ast.walk(tree)
    if isinstance(node, ast.FunctionDef) and node.name == "create_client"
)
create_client_source = ast.get_source_segment(connector, create_client) or ""

checks = {
    "target_1_12_125": target == "1.12.125",
    "connector_matches_target": f'CONNECTOR_VERSION = "{target}"' in connector,
    "engine_matches_target": f'ENGINE_VERSION = "{target}"' in telemetry,
    "automatic_ceiling_preserved": "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in telemetry,
    "automatic_login_receives_ceiling": "self.telemetry_network_timeout_seconds" in telemetry,
    "factory_does_not_restore_12_second_floor": "max(12, min(45" not in create_client_source,
    "factory_accepts_short_telemetry_timeout": "max(1, min(45, int(request_timeout_seconds)))" in create_client_source,
    "published_version_stays_previous_until_ci": 'version: "1.12.124"' in config,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("1.12.125 contract failed: " + ", ".join(failed))

print({"ok": True, "checks": len(checks), "version": target})
