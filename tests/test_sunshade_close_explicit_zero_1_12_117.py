from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "leaphub_gateway"))

import connector  # noqa: E402


class Recorder:
    def __init__(self) -> None:
        self.values: list[str] = []

    def __call__(self, vehicle_id: str, *, value: str):
        self.values.append(value)
        return {"code": 0}


def test_sunshade_close_uses_explicit_native_zero_once():
    recorder = Recorder()
    connector.execute_vehicle_command(recorder, "sunshade_close", "VIN", {})
    assert recorder.values == ["0"]


def test_sunshade_position_extremes_remain_unchanged():
    closed = Recorder()
    connector.execute_vehicle_command(
        closed, "sunshade_position", "VIN", {"sunshade_position": 0}
    )
    assert closed.values == ["0"]

    opened = Recorder()
    connector.execute_vehicle_command(
        opened, "sunshade_position", "VIN", {"sunshade_position": 100}
    )
    assert opened.values == ["10"]


def test_sunshade_open_and_physical_safety_contracts_are_frozen():
    assert connector.COMMAND_METHODS["sunshade_open"] == "open_sunshade"
    assert connector.COMMAND_METHODS["sunshade_close"] == "control_sunshade"
    assert connector.COMMAND_METHODS["sunshade_position"] == "control_sunshade"
    assert connector.COMMAND_REQUIRED_RIGHT["sunshade_close"] == 161
    assert connector.COMMAND_REQUIRED_RIGHT["sunshade_open"] == 161
    assert "sunshade_open" not in connector.ACK_FIRST_COMMANDS
    assert "sunshade_close" not in connector.ACK_FIRST_COMMANDS
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}


def test_unrelated_window_mappings_are_unchanged():
    assert connector.COMMAND_METHODS["windows_open"] == "open_windows"
    assert connector.COMMAND_METHODS["windows_close"] == "close_windows"
