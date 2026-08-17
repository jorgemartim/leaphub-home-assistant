from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))

spec = importlib.util.spec_from_file_location("gateway_112107_connector", APP / "connector.py")
assert spec is not None and spec.loader is not None
connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector)

EXPECTED = {
    "circle": "in",
    "mode": "hot",
    "operate": "manual",
    "position": "all",
    "temperature": "32",
    "windlevel": "7",
    "wshld": "2",
}


def test_release_version_is_1_12_107_or_newer() -> None:
    parts = tuple(int(part) for part in connector.CONNECTOR_VERSION.split("."))
    assert parts >= (1, 12, 107)


def test_verified_windshield_payload_is_exact() -> None:
    assert connector.windshield_defrost_parameters() == EXPECTED


def test_windshield_dispatch_uses_explicit_wshld_2_once() -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def method(*args: object, **kwargs: object) -> dict[str, bool]:
        calls.append((args, kwargs))
        return {"ok": True}

    result = connector.execute_vehicle_command(
        method,
        "windshield_defrost",
        "VIN-TEST",
        {},
    )
    assert result == {"ok": True}
    assert calls == [(('VIN-TEST',), {"params": EXPECTED})]


def test_quick_heat_dispatch_is_untouched() -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def method(*args: object, **kwargs: object) -> str:
        calls.append((args, kwargs))
        return "ok"

    assert connector.execute_vehicle_command(method, "quick_heat", "VIN-TEST", {}) == "ok"
    assert calls == [(('VIN-TEST',), {})]


def test_auto_payload_and_retry_guards_are_unchanged() -> None:
    auto = connector.climate_auto_parameters({"target_temperature": 24})
    assert auto == {
        "circle": "in",
        "mode": "nohotcold",
        "operate": "auto",
        "position": "all",
        "temperature": "24",
        "windlevel": "5",
        "wshld": "0",
    }
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert "windshield_defrost" not in connector.SAFE_STATE_RETRY_COMMANDS
    assert "windshield_defrost" not in connector.ACK_FIRST_COMMANDS
    assert connector.COMMAND_METHODS["windshield_defrost"] == "windshield_defrost"
