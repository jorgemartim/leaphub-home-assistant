from __future__ import annotations

import importlib.util
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_telemetry():
    for name in ("leaphub_connector", "leaphub_connection_orchestrator", "leaphub_event_transport", "_leaphub_193_test"):
        sys.modules.pop(name, None)

    orchestrator = types.ModuleType("leaphub_connection_orchestrator")
    orchestrator.ORCHESTRATOR = object()
    sys.modules[orchestrator.__name__] = orchestrator

    event_transport = types.ModuleType("leaphub_event_transport")
    event_transport.EVENT_TRANSPORT = object()
    sys.modules[event_transport.__name__] = event_transport

    connector_spec = importlib.util.spec_from_file_location("leaphub_connector", APP / "connector.py")
    assert connector_spec and connector_spec.loader
    connector = importlib.util.module_from_spec(connector_spec)
    sys.modules["leaphub_connector"] = connector
    connector_spec.loader.exec_module(connector)

    telemetry_spec = importlib.util.spec_from_file_location("_leaphub_193_test", APP / "telemetry_engine.py")
    assert telemetry_spec and telemetry_spec.loader
    telemetry = importlib.util.module_from_spec(telemetry_spec)
    telemetry_spec.loader.exec_module(telemetry)
    return telemetry


def make_engine(telemetry):
    engine = telemetry.TelemetryEngine.__new__(telemetry.TelemetryEngine)
    engine._confirmation_arm_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-confirm-arm")
    return engine


def result_pending():
    return {
        "command_dispatched": True,
        "cloud_accepted": True,
        "confirmation_pending": True,
    }


def payload(command: str, request_id: str):
    return {
        "command": command,
        "vehicle_id": "vehicle-test",
        "request_id": request_id,
        "parameters": {"nested": {"value": 1}},
    }


def test_slow_local_arm_does_not_delay_accepted_command_path():
    telemetry = load_telemetry()
    engine = make_engine(telemetry)
    entered = threading.Event()
    release = threading.Event()

    def slow_arm(_sid, _payload, _result):
        entered.set()
        assert release.wait(3)

    engine._arm_command_confirmation = slow_arm
    result = result_pending()
    started = time.monotonic()
    queued = engine._queue_command_confirmation_arm("sub", payload("unlock", "r1"), result)
    elapsed = time.monotonic() - started

    assert queued is True
    assert elapsed < 0.20
    assert result["confirmation_arm_queued"] is True
    assert result["confirmation_arm_state"] == "queued"
    assert result["confirmation_armed_by_gateway"] is True
    assert entered.wait(1)
    release.set()
    engine._confirmation_arm_pool.shutdown(wait=True, cancel_futures=False)


def test_confirmation_arm_jobs_are_fifo_for_opposite_intentions():
    telemetry = load_telemetry()
    engine = make_engine(telemetry)
    first_entered = threading.Event()
    release_first = threading.Event()
    order = []

    def ordered_arm(_sid, p, _result):
        order.append(p["command"])
        if p["command"] == "trunk_open":
            first_entered.set()
            assert release_first.wait(3)

    engine._arm_command_confirmation = ordered_arm
    assert engine._queue_command_confirmation_arm("sub", payload("trunk_open", "a"), result_pending())
    assert first_entered.wait(1)
    assert engine._queue_command_confirmation_arm("sub", payload("trunk_close", "b"), result_pending())
    time.sleep(0.05)
    assert order == ["trunk_open"]
    release_first.set()
    engine._confirmation_arm_pool.shutdown(wait=True, cancel_futures=False)
    assert order == ["trunk_open", "trunk_close"]


def test_background_job_uses_copied_metadata_not_mutable_caller_objects():
    telemetry = load_telemetry()
    engine = make_engine(telemetry)
    release = threading.Event()
    captured = []

    def arm(_sid, p, r):
        assert release.wait(3)
        captured.append((p, r))

    engine._arm_command_confirmation = arm
    original_payload = payload("sunshade_close", "copy-test")
    original_result = result_pending()
    assert engine._queue_command_confirmation_arm("sub", original_payload, original_result)

    original_payload["command"] = "sunshade_open"
    original_payload["parameters"]["nested"]["value"] = 99
    original_result["confirmation_pending"] = False
    release.set()
    engine._confirmation_arm_pool.shutdown(wait=True, cancel_futures=False)

    p, r = captured[0]
    assert p["command"] == "sunshade_close"
    assert p["parameters"]["nested"]["value"] == 1
    assert r["confirmation_pending"] is True


def test_shutdown_path_does_not_force_cancel_confirmation_jobs():
    source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    assert "confirmation_pool.shutdown(wait=True, cancel_futures=False)" in source
    assert "max_workers=1" in source
    assert 'thread_name_prefix="leaphub-confirm-arm"' in source
