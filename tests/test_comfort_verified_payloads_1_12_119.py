from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))

import connector  # noqa: E402


class ComfortClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.legacy_calls = 0

    def steering_wheel_heat_on(self, _vin: str):
        self.legacy_calls += 1

    def steering_wheel_heat_off(self, _vin: str):
        self.legacy_calls += 1

    def rearview_mirror_heat_on(self, _vin: str):
        self.legacy_calls += 1

    def rearview_mirror_heat_off(self, _vin: str):
        self.legacy_calls += 1

    def _remote_control(self, *, vin: str, action: str, cmd_content: str):
        self.calls.append({"vin": vin, "action": action, "cmd_content": cmd_content})
        return {"code": 0}


@pytest.mark.parametrize(
    ("command", "expected_content"),
    [
        ("steering_wheel_heat_on", '{"level":"2"}'),
        ("steering_wheel_heat_off", '{"level":"1"}'),
        ("rearview_mirror_heat_on", '{"value":"2"}'),
        ("rearview_mirror_heat_off", '{"value":"1"}'),
    ],
)
def test_comfort_commands_override_legacy_library_payload_once(
    command: str, expected_content: str
) -> None:
    client = ComfortClient()
    method = getattr(client, command)

    result = connector.execute_vehicle_command(method, command, "VIN", {})

    assert result == {"code": 0}
    assert client.legacy_calls == 0
    assert client.calls == [
        {"vin": "VIN", "action": command, "cmd_content": expected_content}
    ]


def test_comfort_override_fails_closed_without_supported_primitive() -> None:
    def unsupported(_vin: str):
        raise AssertionError("payload legado não pode ser enviado")

    with pytest.raises(RuntimeError, match="payload de conforto verificado"):
        connector.execute_vehicle_command(
            unsupported, "steering_wheel_heat_on", "VIN", {}
        )


def test_comfort_commands_keep_physical_safety_contracts() -> None:
    commands = set(connector.VERIFIED_COMFORT_COMMAND_CONTENT)
    assert commands == {
        "steering_wheel_heat_on",
        "steering_wheel_heat_off",
        "rearview_mirror_heat_on",
        "rearview_mirror_heat_off",
    }
    assert commands.isdisjoint(connector.SAFE_STATE_RETRY_COMMANDS)
    assert commands.isdisjoint(connector.ACK_FIRST_COMMANDS)
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}


def test_release_does_not_touch_persistence_or_dependencies() -> None:
    assert (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip() == "1.12.119"
    config = (APP / "config.yaml").read_text(encoding="utf-8")
    assert ('version: "1.12.118"' in config) != ('version: "1.12.119"' in config)
    assert (APP / "requirements.txt").read_text(encoding="utf-8").splitlines() == [
        "leapmotor-api==0.3.2",
        "cryptography==50.0.0",
        "Pillow==12.3.0",
    ]
