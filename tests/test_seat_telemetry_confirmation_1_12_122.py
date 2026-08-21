from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


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
telemetry = load("leaphub_telemetry_seat_112122", APP / "telemetry_engine.py")


def bare_engine():
    return object.__new__(telemetry.TelemetryEngine)


def test_raw_c10_signals_fill_only_missing_typed_seat_fields() -> None:
    actual = connector.enrich_seat_comfort_from_raw(
        {"driver_heating": 2.0, "steering_wheel_heating": 1.0},
        {
            "signal.2100": 3,
            "signal.2101": "1",
            "signal.2118": 2,
            "signal.2119": "0",
        },
    )
    assert actual == {
        "driver_heating": 2.0,
        "driver_ventilation": 1.0,
        "passenger_heating": 2.0,
        "passenger_ventilation": 0.0,
        "steering_wheel_heating": 1.0,
    }


def test_absent_raw_signals_do_not_invent_a_seat_state() -> None:
    assert connector.enrich_seat_comfort_from_raw({}, {}) == {}
    assert connector.enrich_seat_comfort_from_raw({}, {"signal.2100": None}) == {}


@pytest.mark.parametrize(
    ("command", "position", "field"),
    [
        ("seat_heat", "driver", "driver_heating"),
        ("seat_heat", "copilot", "passenger_heating"),
        ("seat_ventilation", "driver", "driver_ventilation"),
        ("seat_ventilation", "copilot", "passenger_ventilation"),
    ],
)
@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_each_seat_and_level_is_confirmed_from_telemetry(
    command: str, position: str, field: str, level: int
) -> None:
    assert command in telemetry.TELEMETRY_CONFIRMABLE_COMMANDS
    engine = bare_engine()
    context = {"parameters": {"seat_position": position, "seat_level": str(level)}}
    assert engine._command_confirmation(
        command, {"seat_comfort": {field: level}}, context
    ) == (True, True)
    assert engine._command_confirmation(
        command, {"seat_comfort": {field: (level + 1) % 4}}, context
    ) == (False, True)


def test_missing_or_invalid_seat_context_is_inconclusive() -> None:
    engine = bare_engine()
    telemetry_sample = {"seat_comfort": {"driver_heating": 1}}
    assert engine._command_confirmation("seat_heat", telemetry_sample, {}) == (False, False)
    assert engine._command_confirmation(
        "seat_heat", telemetry_sample, {"parameters": {"seat_position": "rear", "seat_level": 1}}
    ) == (False, False)
    assert engine._command_confirmation(
        "seat_heat", {}, {"parameters": {"seat_position": "driver", "seat_level": 1}}
    ) == (False, False)


def test_generic_parameter_aliases_remain_compatible() -> None:
    engine = bare_engine()
    assert engine._command_confirmation(
        "seat_heat",
        {"seat_comfort": {"passenger_heating": 3}},
        {"parameters": {"position": "passenger", "level": 3}},
    ) == (True, True)

