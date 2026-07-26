from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mqtt_passive_contract_test",
    ROOT / "leaphub_gateway" / "event_transport.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_mqtt_is_passive_and_commands_remain_on_rest() -> None:
    coordinator = MODULE.EventTransportCoordinator()
    state = coordinator.snapshot()
    assert state["mqtt"]["active"] is False
    assert state["mqtt"]["status"] == "awaiting_homologation"
    assert state["command_transport"] == "rest_authenticated"
    assert state["active_telemetry_transport"] == "rest_polling"
    assert state["rest_fallback"] is True


def test_passive_hint_wakes_fast_rest_once_without_command_publication() -> None:
    coordinator = MODULE.EventTransportCoordinator()
    calls: list[tuple[str, int, str, str]] = []
    coordinator.register_wake_callback(
        lambda env, account, vehicle, source: calls.append((env, account, vehicle, source)) or True
    )
    first = coordinator.ingest_hint(
        "staging",
        9,
        "vehicle-safe",
        source="mqtt_passive",
        event_key="state_changed",
    )
    duplicate = coordinator.ingest_hint(
        "staging",
        9,
        "vehicle-safe",
        source="mqtt_passive",
        event_key="state_changed",
    )

    assert first["woken"] is True
    assert duplicate["deduplicated"] is True
    assert calls == [("staging", 9, "vehicle-safe", "mqtt_passive")]

    source = (ROOT / "leaphub_gateway" / "event_transport.py").read_text(encoding="utf-8").lower()
    assert "mqtt.publish" not in source
    assert "publish_command" not in source
