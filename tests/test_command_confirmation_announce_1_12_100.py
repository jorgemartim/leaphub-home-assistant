from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load("leaphub_connector", APP / "connector.py")
telemetry = load("leaphub_telemetry_confirmation_112100", APP / "telemetry_engine.py")


def bare_engine():
    return object.__new__(telemetry.TelemetryEngine)


class ImmediateThread:
    def __init__(self, *, target, name=None, daemon=None):
        self.target = target
        self.name = name
        self.daemon = daemon

    def start(self):
        self.target()


def test_fast_confirmation_is_announced_as_final(monkeypatch):
    engine = bare_engine()
    sent = []

    def fake_announce(environment, request_id, result):
        sent.append((environment, request_id, dict(result)))
        return True

    engine.announce_command_result = fake_announce
    monkeypatch.setattr(telemetry.threading, "Thread", ImmediateThread)

    item = {
        "confirmed": True,
        "request_id": "ref_windows_123",
        "command_key": "windows_close",
        "poll_count": 4,
        "elapsed": 23.9,
    }
    assert engine._announce_telemetry_confirmation_async("staging", item) is True
    assert len(sent) == 1
    environment, request_id, result = sent[0]
    assert environment == "staging"
    assert request_id == "ref_windows_123"
    assert result["confirmation_pending"] is False
    assert result["verified_by_gateway"] is True
    assert result["vehicle_confirmed"] is True
    assert result["applied"] is True
    assert result["final_outcome"] == "confirmed"
    assert result["confirmation_source"] == "telemetry_match"
    assert result["confirmation_reads"] == 4
    assert result["confirmation_elapsed_seconds"] == 23
    assert result["gateway_version"] == "1.12.100"


def test_no_final_announcement_without_positive_verdict(monkeypatch):
    engine = bare_engine()
    sent = []
    engine.announce_command_result = lambda *args, **kwargs: sent.append((args, kwargs)) or True
    monkeypatch.setattr(telemetry.threading, "Thread", ImmediateThread)

    assert engine._announce_telemetry_confirmation_async(
        "staging", {"confirmed": False, "request_id": "ref_pending", "command_key": "windows_open"}
    ) is False
    assert engine._announce_telemetry_confirmation_async(
        "staging", {"confirmed": True, "request_id": "", "command_key": "windows_open"}
    ) is False
    assert sent == []


def test_final_announcement_is_notification_only():
    source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    start = source.index("    def _announce_telemetry_confirmation_async(")
    end = source.index("    def announce_command_result(", start)
    helper = source[start:end]
    assert "threading.Thread" in helper
    assert "self.announce_command_result" in helper
    assert "execute_vehicle_command" not in helper
    assert "boost(" not in helper
