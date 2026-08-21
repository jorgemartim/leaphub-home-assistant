from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))

import connector  # noqa: E402


class SlowResultClient:
    def __init__(self) -> None:
        self.physical_calls: list[dict[str, object]] = []
        self.result_polls = 0

    def _poll_remote_control_result(self, *_args, **_kwargs):
        self.result_polls += 1
        return {"slow_library_poll": True}

    def _remote_control(self, *, vin: str, action: str, cmd_content: str):
        self.physical_calls.append(
            {"vin": vin, "action": action, "cmd_content": cmd_content}
        )
        return self._poll_remote_control_result("request-id")

    def seat_heat(self, _vin: str):
        raise AssertionError("o wrapper legado de banco não pode ser chamado")

    def seat_ventilation(self, _vin: str):
        raise AssertionError("o wrapper legado de banco não pode ser chamado")


class SlowDefrostClient(SlowResultClient):
    def windshield_defrost(self, vin: str, *, params: dict[str, str]):
        self.physical_calls.append({"vin": vin, "action": "windshield_defrost", "params": params})
        return self._poll_remote_control_result("request-id")


@pytest.mark.parametrize("command", ["seat_heat", "seat_ventilation"])
def test_seat_comfort_returns_after_single_dispatch_without_library_result_poll(command: str) -> None:
    client = SlowResultClient()

    result, deferred = connector.execute_vehicle_command_ack_first(
        getattr(client, command),
        command,
        "VIN",
        {"seat_position": "driver", "seat_level": 0},
    )

    assert deferred is True
    assert result == {"deferred": True, "confirmation_source": "gateway_fast_telemetry"}
    assert client.result_polls == 0
    assert len(client.physical_calls) == 1
    assert client.physical_calls[0]["cmd_content"] == '{"position":"driver","level":"0"}'
    # O override é temporário; a biblioteca volta ao comportamento original.
    assert "_poll_remote_control_result" not in client.__dict__


@pytest.mark.parametrize("enabled", [True, False])
def test_defrost_returns_after_single_dispatch_without_library_result_poll(enabled: bool) -> None:
    client = SlowDefrostClient()

    result, deferred = connector.execute_vehicle_command_ack_first(
        client.windshield_defrost,
        "windshield_defrost",
        "VIN",
        {"enabled": enabled},
    )

    assert deferred is True
    assert result == {"deferred": True, "confirmation_source": "gateway_fast_telemetry"}
    assert client.result_polls == 0
    assert len(client.physical_calls) == 1
    expected = connector.windshield_defrost_parameters() if enabled else connector.windshield_defrost_off_parameters()
    assert client.physical_calls[0]["params"] == expected
    assert "_poll_remote_control_result" not in client.__dict__


def test_comfort_fast_ack_never_enables_physical_retry() -> None:
    fast = {"windshield_defrost", "seat_heat", "seat_ventilation"}
    assert fast.issubset(connector.ACK_FIRST_COMMANDS)
    assert fast.isdisjoint(connector.SAFE_STATE_RETRY_COMMANDS)
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}

