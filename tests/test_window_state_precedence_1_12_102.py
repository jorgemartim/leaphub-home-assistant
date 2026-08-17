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


connector = load("leaphub_connector_window_state_112102", APP / "connector.py")


def test_explicit_open_wins_over_stale_zero_percent():
    assert connector.effective_window_open(0.0, True) is True


def test_explicit_closed_wins_over_stale_nonzero_percent():
    assert connector.effective_window_open(100.0, False) is False


def test_percentage_is_fallback_only_when_status_absent():
    assert connector.effective_window_open(0.0, None) is False
    assert connector.effective_window_open(10.0, None) is True
    assert connector.effective_window_open(None, None) is None


def test_all_four_can_be_open_with_stale_rear_percent_zero():
    positions = {"front_left": None, "front_right": None, "rear_left": 0.0, "rear_right": 0.0}
    statuses = {"front_left": True, "front_right": True, "rear_left": True, "rear_right": True}
    states = {key: connector.effective_window_open(positions[key], statuses[key]) for key in positions}
    assert all(states.values())


def test_numeric_window_signal_ids_are_allowlisted_and_unrelated_ids_are_not():
    raw = {"data": {"signal": {
        "3727": 100, "3728": 100, "1879": 0, "1880": 0,
        "1693": 1, "1694": 1, "1695": 1, "1696": 1,
        "3725": 40.0, "1204": 80,
    }}}
    result = connector.safe_window_raw_signals(raw)
    assert result == {
        "data.signal.1693": 1,
        "data.signal.1694": 1,
        "data.signal.1695": 1,
        "data.signal.1696": 1,
        "data.signal.1879": 0,
        "data.signal.1880": 0,
        "data.signal.3727": 100,
        "data.signal.3728": 100,
    }


def test_physical_contracts_unchanged():
    source = (APP / "connector.py").read_text(encoding="utf-8")
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert 'native = 10 if command == "windows_open" else 0' in source
    assert 'native = (position + 5) // 10' in source
    assert 'native = (percent + 5) // 10' in source
