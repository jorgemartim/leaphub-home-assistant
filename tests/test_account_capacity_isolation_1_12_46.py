from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_operation_limiter_exposes_background_waiters():
    server = _load(APP / "connector_server.py", "leaphub_connector_server_146")
    limiter = server.PriorityOperationLimiter(1)
    assert limiter.acquire(timeout=0.1, priority=True)
    done = threading.Event()
    result = {}

    def wait_background():
        result["ok"] = limiter.acquire(timeout=0.35, priority=False)
        done.set()

    worker = threading.Thread(target=wait_background, daemon=True)
    worker.start()
    time.sleep(0.08)
    snap = limiter.snapshot()
    assert snap["active"] == 1
    assert snap["background_waiters"] == 1
    limiter.release()
    assert done.wait(1.0)
    assert result["ok"] is True
    limiter.release()


def test_telemetry_uses_account_before_global_slot_contract():
    source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    anchor = source.index("# 1.12.47 — ordem única de aquisição")
    window = source[anchor: anchor + 8000]
    account = window.index("account_lock.acquire")
    slot = window.index("self.operation_semaphore.acquire")
    assert account < slot
    assert "nenhuma vaga global foi ocupada enquanto aguardava" in window
    assert "global" in window.lower()


def test_diagnostic_export_is_explicitly_sanitized():
    source = (APP / "gateway_manager.py").read_text(encoding="utf-8")
    assert "diagnostic_export_payload" in source
    assert "sanitized_no_logs_no_secrets_no_identifiers" in source
    assert "/api/diagnostics/export" in source
    block = source[source.index("def diagnostic_export_payload"):source.index("def persist_status")]
    assert '"logs"' not in block
    assert "tunnel_token" not in block
    assert "staging_secret" not in block
    assert "production_secret" not in block
