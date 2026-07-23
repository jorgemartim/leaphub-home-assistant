from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
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
load_module("leaphub_telemetry_engine", APP / "telemetry_engine.py")
load_module("leaphub_privacy", APP / "privacy.py")
with tempfile.TemporaryDirectory(prefix="leaphub-health-") as tmp:
    status_path = Path(tmp) / "unified-status.json"
    os.environ["LEAPHUB_MANAGER_STATUS_PATH"] = str(status_path)
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(Path(tmp) / "telemetry")
    os.environ["LEAPHUB_NONCE_DB_PATH"] = str(Path(tmp) / "connector-nonces.sqlite")
    os.environ["LEAPHUB_COMMAND_DB_PATH"] = str(Path(tmp) / "connector-commands.sqlite")
    server = load_module("leaphub_connection_health_test", APP / "connector_server.py")
    server.MANAGER_STATUS_PATH = status_path

    status_path.write_text(json.dumps({
        "services": {
            "connector": {
                "enabled": True,
                "configured": True,
                "state": "running",
                "pid": 123,
                "logs": ["segredo não pode sair"],
                "restarts": 0,
                "health": {"ok": True, "message": "endpoint respondeu"},
            },
            "ocpp_wallbox": {
                "enabled": True,
                "configured": True,
                "state": "running",
                "restarts": 2,
                "health": {"ok": False, "message": "detalhe interno"},
            },
            "tunnel": {
                "enabled": False,
                "configured": False,
                "state": "disabled",
                "restarts": 0,
                "health": {"ok": False},
            },
        }
    }), encoding="utf-8")

    health = server.gateway_services_health()
    assert health["connector"]["state"] == "healthy"
    assert health["ocpp"]["state"] == "degraded"
    assert health["tunnel"]["state"] == "disabled"
    encoded = json.dumps(health)
    assert "logs" not in encoded
    assert "pid" not in encoded
    assert "segredo" not in encoded
    assert "detalhe interno" not in encoded

    old = time.time() - 120
    os.utime(status_path, (old, old))
    assert server.gateway_services_health() == {}

print({"ok": True, "checks": 9, "version": "1.12.22"})
