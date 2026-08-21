from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_connector():
    spec = importlib.util.spec_from_file_location(
        "leaphub_seat_verified_1_12_121", APP / "connector.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


connector = load_connector()


class Client:
    def __init__(self) -> None:
        self.remote_calls: list[dict[str, str]] = []
        self.legacy_calls = 0

    def seat_heat(self, _vin: str, *, position: int, level: int):
        self.legacy_calls += 1

    def seat_ventilation(self, _vin: str, *, position: int, level: int):
        self.legacy_calls += 1

    def _remote_control(self, *, vin: str, action: str, cmd_content: str):
        self.remote_calls.append(
            {"vin": vin, "action": action, "cmd_content": cmd_content}
        )
        return {"code": 0}


@pytest.mark.parametrize("command", ["seat_heat", "seat_ventilation"])
@pytest.mark.parametrize("position", ["driver", "copilot"])
@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_every_supported_side_and_level_has_an_exact_payload(
    command: str, position: str, level: int
) -> None:
    client = Client()

    result = connector.execute_vehicle_command(
        getattr(client, command),
        command,
        "VIN",
        {"seat_position": position, "seat_level": str(level)},
    )

    assert result == {"code": 0}
    assert client.legacy_calls == 0
    assert len(client.remote_calls) == 1
    call = client.remote_calls[0]
    assert call["action"] == command
    assert json.loads(call["cmd_content"]) == {
        "position": position,
        "level": str(level),
    }


def test_numeric_wrapper_payload_can_never_be_sent_again() -> None:
    client = Client()

    with pytest.raises(ValueError, match="Assento inválido"):
        connector.execute_vehicle_command(
            client.seat_heat,
            "seat_heat",
            "VIN",
            {"seat_position": 3, "seat_level": 3},
        )

    assert client.legacy_calls == 0
    assert client.remote_calls == []


def test_missing_raw_primitive_fails_closed() -> None:
    class Unsupported:
        def seat_heat(self, _vin: str, *, position: int, level: int):
            raise AssertionError("o wrapper legado não pode ser usado")

    with pytest.raises(RuntimeError, match="payload de banco verificado"):
        connector.execute_vehicle_command(
            Unsupported().seat_heat,
            "seat_heat",
            "VIN",
            {"seat_position": "driver", "seat_level": 3},
        )


def test_release_is_staged_without_dependency_or_data_changes() -> None:
    version = tuple(int(part) for part in connector.CONNECTOR_VERSION.split("."))
    target = tuple(int(part) for part in (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip().split("."))
    assert version >= (1, 12, 121)
    assert target >= (1, 12, 121)
    assert (APP / "requirements.txt").read_text(encoding="utf-8").splitlines() == [
        "leapmotor-api==0.3.2",
        "cryptography==50.0.0",
        "Pillow==12.3.0",
    ]
    source = (APP / "connector.py").read_text(encoding="utf-8")
    assert '"position": position, "level": str(level)' in source
    assert 'method(vehicle_id, position=position, level=level)' not in source

