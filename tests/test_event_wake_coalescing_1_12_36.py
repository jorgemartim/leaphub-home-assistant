from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("event_transport_coalesce_test", ROOT / "leaphub_gateway" / "event_transport.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
EventTransportCoordinator = MODULE.EventTransportCoordinator


def test_distinct_events_for_same_target_coalesce_only_the_wakeup() -> None:
    coordinator = EventTransportCoordinator()
    calls: list[tuple[str, int, str, str]] = []
    coordinator.register_wake_callback(lambda env, account, vehicle, source: calls.append((env, account, vehicle, source)) or True)

    first = coordinator.ingest_hint("staging", 7, "vehicle-x", source="command_result", event_key="command:lock")
    second = coordinator.ingest_hint("staging", 7, "vehicle-x", source="telemetry_push", event_key="state_changed")

    assert first["woken"] is True and first["wake_coalesced"] is False
    assert second["deduplicated"] is False
    assert second["woken"] is False and second["wake_coalesced"] is True
    assert len(calls) == 1
    state = coordinator.snapshot()["event_hints"]
    assert state["accepted"] == 2
    assert state["wakeups"] == 1
    assert state["coalesced_wakeups"] == 1
