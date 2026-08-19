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


connector = load("leaphub_connector_diag_112116", APP / "connector.py")


def _sample():
    positions = {
        "front_left": 100,
        "front_right": 100,
        "rear_left": None,
        "rear_right": None,
    }
    states = {
        "front_left": True,
        "front_right": True,
        "rear_left": None,
        "rear_right": None,
    }
    raw = {"windows.rearLeftSignal": 1}
    return positions, states, raw


def test_vehicle_token_is_stable_and_redacted():
    raw = "remote-vehicle-123456"
    first = connector.window_diag_vehicle_token(raw)
    second = connector.window_diag_vehicle_token(raw)
    assert first == second
    assert first.startswith("veh_")
    assert raw not in first


def test_different_vehicles_have_different_tokens():
    assert connector.window_diag_vehicle_token("vehicle-a") != connector.window_diag_vehicle_token("vehicle-b")


def test_unknown_vehicle_token_is_explicit():
    assert connector.window_diag_vehicle_token("") == "veh_unknown"


def test_legacy_three_argument_call_remains_compatible(monkeypatch):
    connector._WINDOW_RAW_DIAG_LAST_SIGNATURE = None
    connector._WINDOW_RAW_DIAG_LAST_SIGNATURES.clear()
    seen = []
    monkeypatch.setattr(connector, "connector_log", lambda *args: seen.append(args))
    positions, states, raw = _sample()

    assert connector.log_window_telemetry_diag(positions, states, raw) is True
    assert connector.log_window_telemetry_diag(positions, states, raw) is False
    assert len(seen) == 1


def test_dedupe_is_isolated_per_vehicle(monkeypatch):
    connector._WINDOW_RAW_DIAG_LAST_SIGNATURE = None
    connector._WINDOW_RAW_DIAG_LAST_SIGNATURES.clear()
    seen = []
    monkeypatch.setattr(connector, "connector_log", lambda *args: seen.append(args))
    positions, states, raw = _sample()

    assert connector.log_window_telemetry_diag(
        positions, states, raw, vehicle_key="vehicle-a"
    ) is True
    assert connector.log_window_telemetry_diag(
        positions, states, raw, vehicle_key="vehicle-a"
    ) is False
    assert connector.log_window_telemetry_diag(
        positions, states, raw, vehicle_key="vehicle-b"
    ) is True

    assert len(seen) == 2
    first_message = seen[0][1]
    assert "WINDOW_TELEMETRY_DIAG vehicle=%s" in first_message
    assert "vehicle-a" not in repr(seen[0])
    assert "vehicle-b" not in repr(seen[1])


def test_physical_command_contracts_not_changed_by_diagnostic_candidate():
    source = (APP / "connector.py").read_text(encoding="utf-8")
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert "windows_open" not in connector.ACK_FIRST_COMMANDS
    assert "windows_close" not in connector.ACK_FIRST_COMMANDS
    assert "sunshade_open" not in connector.ACK_FIRST_COMMANDS
    assert "sunshade_close" not in connector.ACK_FIRST_COMMANDS
    assert 'native = 10 if command == "windows_open" else 0' in source
