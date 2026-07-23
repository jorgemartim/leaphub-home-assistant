from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_confirmation_test", APP / "telemetry_engine.py")
server_source = (APP / "connector_server.py").read_text(encoding="utf-8")
manager_source = (APP / "gateway_manager.py").read_text(encoding="utf-8")
config_source = (APP / "config.yaml").read_text(encoding="utf-8")

with tempfile.TemporaryDirectory(prefix="leaphub-confirmation-") as tmp:
    os.environ["LEAPHUB_TELEMETRY_DIR"] = tmp
    engine = telemetry.TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": "https://example.invalid/telemetry",
            "telemetry_background_enabled": True,
            "telemetry_command_seconds": 12,
            # Simula a opção preservada de uma instalação 1.12.21.
            "telemetry_command_max_polls": 3,
        },
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )
    assert engine.command_max_polls == 5
    assert list(engine.command_cadence[:5]) == [12, 20, 35, 45, 60]
    assert engine._adaptive_interval(["parked"], 0, command_mode=True, command_poll_count=1)[0] == 12
    assert engine._adaptive_interval(["parked"], 0, command_mode=True, command_poll_count=5)[0] == 60
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()

checks = {
    "version": 'version: "1.12.22"' in config_source
        and 'VERSION = "1.12.22"' in server_source,
    "manager_migrates_legacy_limit": 'max(5, min(8' in manager_source,
    "private_posts_close": "def do_POST(self) -> None:\n        # As chamadas assinadas" in server_source
        and "self.close_connection = True" in server_source,
    "close_header_uses_handler_state": 'close_connection or bool(getattr(self, "close_connection", False))' in server_source,
    "public_health_stays_keepalive": "public_health_payload(), close_connection=True" not in server_source,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("remote confirmation 1.12.22 failed:\n- " + "\n- ".join(failed))

print({"ok": True, "checks": len(checks) + 4, "version": "1.12.22"})
