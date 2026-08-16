from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

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
telemetry = load("leaphub_telemetry_windows_112100", APP / "telemetry_engine.py")


def bare_engine():
    return object.__new__(telemetry.TelemetryEngine)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, vin, **kwargs):
        self.calls.append((vin, kwargs))
        return {"ok": True}


def test_model_scale_is_c10_b10_only():
    assert connector.window_command_native_scale(SimpleNamespace(car_type="C10")) == 10
    assert connector.window_command_native_scale(SimpleNamespace(car_type="C10 REEV")) == 10
    assert connector.window_command_native_scale(SimpleNamespace(car_type="B10")) == 10
    assert connector.window_command_native_scale(SimpleNamespace(car_type="T03")) == 100
    assert connector.window_command_native_scale(SimpleNamespace(car_type="C16")) == 100
    assert connector.window_command_native_scale(None) == 100


def test_c10_position_maps_every_ui_step_to_0_10():
    cases = [(0, "0"), (10, "1"), (20, "2"), (30, "3"), (40, "4"),
             (50, "5"), (60, "6"), (70, "7"), (80, "8"), (90, "9"), (100, "10")]
    for percent, native in cases:
        rec = Recorder()
        connector.execute_vehicle_command(
            rec, "windows_position", "VIN", {"window_position": percent}, window_native_scale=10
        )
        assert rec.calls == [("VIN", {"value": native})]


def test_c10_open_close_each_send_once_with_native_extreme():
    opened = Recorder()
    connector.execute_vehicle_command(opened, "windows_open", "VIN", {}, window_native_scale=10)
    assert opened.calls == [("VIN", {"value": "10"})]

    closed = Recorder()
    connector.execute_vehicle_command(closed, "windows_close", "VIN", {}, window_native_scale=10)
    assert closed.calls == [("VIN", {"value": "0"})]


def test_t03_unknown_preserves_previous_0_100_behavior():
    opened = Recorder()
    connector.execute_vehicle_command(opened, "windows_open", "VIN", {}, window_native_scale=100)
    assert opened.calls == [("VIN", {})]

    positioned = Recorder()
    connector.execute_vehicle_command(
        positioned, "windows_position", "VIN", {"window_position": 40}, window_native_scale=100
    )
    assert positioned.calls == [("VIN", {"value": "40"})]


def test_windows_never_join_safe_retry_and_sunshade_is_unchanged():
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    for command in ("windows_open", "windows_close", "windows_position"):
        assert command not in connector.SAFE_STATE_RETRY_COMMANDS

    source = (APP / "connector.py").read_text(encoding="utf-8")
    start = source.index('    if command == "sunshade_position":')
    end = source.index('    if command == "set_speed_limit":', start)
    block = source[start:end]
    assert "native = (percent + 5) // 10" in block
    assert 'return method(vehicle_id, value=str(native))' in block
    assert "sunshade_position" not in connector.ACK_FIRST_COMMANDS


def test_windows_position_is_confirmable_and_same_supersession_family():
    assert "windows_position" in telemetry.TELEMETRY_CONFIRMABLE_COMMANDS
    assert telemetry.CONFIRMATION_SUPERSESSION_FAMILIES["windows"] == frozenset({
        "windows_open", "windows_close", "windows_position"
    })
    assert telemetry.TelemetryEngine.COMMAND_CONFIRMATION_FIELDS["windows_position"] == (
        "window_positions",
    )


def test_position_confirmation_requires_all_four():
    engine = bare_engine()
    context = {"parameters": {"window_position": 50}}

    all_half = {"window_positions": {
        "front_left": 50, "front_right": 50, "rear_left": 50, "rear_right": 50,
    }}
    assert engine._command_confirmation("windows_position", all_half, context) == (True, True)

    one_wrong = {"window_positions": {
        "front_left": 50, "front_right": 50, "rear_left": 20, "rear_right": 50,
    }}
    assert engine._command_confirmation("windows_position", one_wrong, context) == (False, True)

    incomplete = {"window_positions": {
        "front_left": 50, "front_right": 50, "rear_left": 50,
    }}
    assert engine._command_confirmation("windows_position", incomplete, context) == (False, False)


def test_open_close_require_all_four_not_any_one():
    engine = bare_engine()
    only_one_open = {"window_positions": {
        "front_left": 100, "front_right": 20, "rear_left": 20, "rear_right": 20,
    }}
    assert engine._command_confirmation("windows_open", only_one_open, {"parameters": {}}) == (False, True)

    all_open = {"window_positions": {
        "front_left": 100, "front_right": 100, "rear_left": 90, "rear_right": 100,
    }}
    assert engine._command_confirmation("windows_open", all_open, {"parameters": {}}) == (True, True)

    all_closed = {"window_positions": {
        "front_left": 0, "front_right": 0, "rear_left": 0, "rear_right": 0,
    }}
    assert engine._command_confirmation("windows_close", all_closed, {"parameters": {}}) == (True, True)


def test_boolean_fallback_requires_all_four_known():
    engine = bare_engine()
    partial = {"windows": {
        "front_left": True, "front_right": True, "rear_left": True,
    }}
    assert engine._command_confirmation("windows_open", partial, {"parameters": {}}) == (False, False)

    all_open = {"windows": {
        "front_left": True, "front_right": True, "rear_left": True, "rear_right": True,
    }}
    assert engine._command_confirmation("windows_open", all_open, {"parameters": {}}) == (True, True)
