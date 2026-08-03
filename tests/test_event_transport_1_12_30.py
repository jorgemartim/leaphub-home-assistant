from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("event_transport_test", ROOT / "leaphub_gateway" / "event_transport.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
EventTransportCoordinator = MODULE.EventTransportCoordinator

TELEMETRY = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
DOCKER = (ROOT / "leaphub_gateway" / "Dockerfile").read_text(encoding="utf-8")


def test_event_hints_are_deduplicated_and_wake_once() -> None:
    coordinator = EventTransportCoordinator()
    calls: list[tuple[str, int, str, str]] = []
    coordinator.register_wake_callback(lambda env, account, vehicle, source: calls.append((env, account, vehicle, source)) or True)
    first = coordinator.ingest_hint("staging", 7, "vehicle-x", source="mqtt", event_key="status")
    second = coordinator.ingest_hint("staging", 7, "vehicle-x", source="mqtt", event_key="status")
    assert first == {"accepted": True, "deduplicated": False, "woken": True, "wake_coalesced": False}
    assert second == {"accepted": True, "deduplicated": True, "woken": False}
    assert len(calls) == 1


def test_mqtt_is_not_claimed_active_before_homologation() -> None:
    coordinator = EventTransportCoordinator()
    state = coordinator.snapshot()
    assert state["preferred_strategy"] == "events_then_rest"
    assert state["active_telemetry_transport"] == "rest_polling"
    assert state["command_transport"] == "rest_authenticated"
    assert state["rest_fallback"] is True
    assert state["mqtt"]["active"] is False
    assert state["mqtt"]["status"] == "awaiting_homologation"


def test_event_layer_is_wired_without_new_physical_command_path() -> None:
    assert 'ENGINE_VERSION = "1.12.72"' in TELEMETRY
    assert 'EVENT_TRANSPORT.register_wake_callback(self._wake_from_event)' in TELEMETRY
    assert '"event_transport": EVENT_TRANSPORT.snapshot()' in SERVER
    assert 'event_transport.py' in DOCKER
    assert 'mqtt' not in SERVER.lower().split('def run_command_job', 1)[1].split('def start_command_job', 1)[0]
