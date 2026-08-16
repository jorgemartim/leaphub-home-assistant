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


connector = load("leaphub_connector_diag_112101", APP / "connector.py")


def test_safe_window_raw_signals_keeps_only_window_like_scalars():
    raw = {
        "body": {
            "leftRearWindowPercent": 100,
            "rightRearWindowPercent": 100,
            "temperature": 23,
        },
        "windows": {
            "101": 0,
            "102": 100,
            "nested": {"windowState": "open"},
        },
    }
    result = connector.safe_window_raw_signals(raw)
    assert result["body.leftRearWindowPercent"] == 100
    assert result["body.rightRearWindowPercent"] == 100
    assert result["windows.101"] == 0
    assert result["windows.102"] == 100
    assert result["windows.nested.windowState"] == "open"
    assert "body.temperature" not in result


def test_safe_window_raw_signals_excludes_sensitive_paths():
    raw = {
        "window": {
            "leftRearPercent": 100,
            "vin": "WLM123456789",
            "gps": {"windowDebug": 20},
            "token": "secret",
            "account": {"window": 100},
            "location": {"window": 100},
        },
        "deviceId": {"window": 100},
        "privateKey": {"window": 100},
    }
    result = connector.safe_window_raw_signals(raw)
    assert result == {"window.leftRearPercent": 100}


def test_diag_is_bounded():
    raw = {"windows": {f"signal{i}": i for i in range(200)}}
    result = connector.safe_window_raw_signals(raw, max_items=12)
    assert len(result) == 12


def test_log_only_when_snapshot_changes(monkeypatch):
    connector._WINDOW_RAW_DIAG_LAST_SIGNATURE = None
    seen = []
    monkeypatch.setattr(connector, "connector_log", lambda *args: seen.append(args))
    positions = {"front_left": 100, "front_right": 100, "rear_left": None, "rear_right": None}
    states = {"front_left": True, "front_right": True, "rear_left": None, "rear_right": None}
    raw = {"windows.rearLeftSignal": 1}
    assert connector.log_window_telemetry_diag(positions, states, raw) is True
    assert connector.log_window_telemetry_diag(positions, states, raw) is False
    assert len(seen) == 1


def test_physical_contracts_unchanged():
    source = (APP / "connector.py").read_text(encoding="utf-8")
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert 'native = 10 if command == "windows_open" else 0' in source
    assert 'native = (position + 5) // 10' in source
    assert 'native = (percent + 5) // 10' in source
