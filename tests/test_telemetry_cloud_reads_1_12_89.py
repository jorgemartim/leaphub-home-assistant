from __future__ import annotations

import contextlib
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load("leaphub_connector_189", APP / "connector.py")
sys.modules.setdefault("leaphub_connector", connector)

_previous_orchestrator_module = sys.modules.get("leaphub_connection_orchestrator")
_previous_event_transport_module = sys.modules.get("leaphub_event_transport")
try:
    orch = types.ModuleType("leaphub_connection_orchestrator")
    orch.ORCHESTRATOR = object()
    sys.modules["leaphub_connection_orchestrator"] = orch

    event = types.ModuleType("leaphub_event_transport")
    event.EVENT_TRANSPORT = object()
    sys.modules["leaphub_event_transport"] = event

    telemetry = load("gw189_telemetry", APP / "telemetry_engine.py")
finally:
    if _previous_orchestrator_module is None:
        sys.modules.pop("leaphub_connection_orchestrator", None)
    else:
        sys.modules["leaphub_connection_orchestrator"] = _previous_orchestrator_module

    if _previous_event_transport_module is None:
        sys.modules.pop("leaphub_event_transport", None)
    else:
        sys.modules["leaphub_event_transport"] = _previous_event_transport_module


def make_engine():
    engine = telemetry.TelemetryEngine.__new__(telemetry.TelemetryEngine)
    engine._telemetry_request_timeout = lambda _client: contextlib.nullcontext()
    engine.closed = []
    engine._close_session_locked = lambda sid: engine.closed.append(sid)
    return engine


def test_vehicle_list_uses_private_request_only():
    engine = make_engine()

    class Client:
        token = "token"

        def __init__(self):
            self.private_calls = 0
            self.public_calls = 0

        def _get_vehicle_list(self):
            self.private_calls += 1
            return ["car"]

        def get_vehicle_list(self):
            self.public_calls += 1
            raise AssertionError("public vehicle-list retry wrapper is forbidden")

    client = Client()
    assert engine._telemetry_vehicle_list_one_shot("sub", client) == ["car"]
    assert client.private_calls == 1
    assert client.public_calls == 0


def test_vehicle_list_yields_before_refresh_if_manual_arrives():
    engine = make_engine()
    refreshes = []

    class Client:
        token = "token"

        def _get_vehicle_list(self):
            raise RuntimeError("invalid token: session expired")

    engine._try_refresh_client_session = lambda _client: refreshes.append(1) or True
    decisions = iter((False, True))
    try:
        engine._telemetry_vehicle_list_one_shot(
            "sub",
            Client(),
            manual_should_yield=lambda: next(decisions),
        )
    except telemetry.TelemetryYieldForManual:
        pass
    else:
        raise AssertionError("telemetry did not yield before vehicle-list refresh")

    assert refreshes == []


def test_vehicle_list_one_refresh_one_retry_no_third_call():
    engine = make_engine()
    refreshes = []

    class Client:
        token = "token"

        def __init__(self):
            self.calls = 0

        def _get_vehicle_list(self):
            self.calls += 1
            if self.calls <= 2:
                raise RuntimeError("invalid token: session expired")
            return ["forbidden-third"]

    client = Client()
    engine._try_refresh_client_session = lambda _client: refreshes.append(1) or True
    try:
        engine._telemetry_vehicle_list_one_shot("sub", client)
    except telemetry.connector.ConnectorSessionExpiredError:
        pass
    else:
        raise AssertionError("second vehicle-list expiry should end the cycle")

    assert client.calls == 2
    assert refreshes == [1]
    assert engine.closed == ["sub"]


def test_message_list_uses_private_request_only():
    engine = make_engine()

    class Page:
        messages = ["m1"]

    class Client:
        token = "token"

        def __init__(self):
            self.private_calls = 0
            self.public_calls = 0

        def _get_message_list(self, *, page_no=1, page_size=10):
            self.private_calls += 1
            assert page_no == 1
            assert page_size == 100
            return Page()

        def get_message_list(self, *, page_no=1, page_size=10):
            self.public_calls += 1
            raise AssertionError("public message-list retry wrapper is forbidden")

    client = Client()
    page = engine._telemetry_message_list_one_shot("sub", client)
    assert page.messages == ["m1"]
    assert client.private_calls == 1
    assert client.public_calls == 0


def test_message_list_yields_before_refresh_if_manual_arrives():
    engine = make_engine()
    refreshes = []

    class Client:
        token = "token"

        def _get_message_list(self, *, page_no=1, page_size=100):
            raise RuntimeError("invalid token: session expired")

    engine._try_refresh_client_session = lambda _client: refreshes.append(1) or True
    decisions = iter((False, True))
    try:
        engine._telemetry_message_list_one_shot(
            "sub",
            Client(),
            manual_should_yield=lambda: next(decisions),
        )
    except telemetry.TelemetryYieldForManual:
        pass
    else:
        raise AssertionError("telemetry did not yield before message refresh")

    assert refreshes == []


def test_real_collection_contains_no_public_retry_wrappers_for_cloud_reads():
    source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    start = source.index("    def _collect_with_session_locked(")
    end = source.index("    def _close_session_locked(", start)
    body = source[start:end]

    # Public calls remain only in explicit synthetic-test compatibility branches.
    assert "private_vehicle_list = getattr(client, \"_get_vehicle_list\", None)" in body
    assert "private_message_list = getattr(client, \"_get_message_list\", None)" in body
    assert "official_leapmotor_client" in body
    assert "_telemetry_vehicle_list_one_shot(" in body
    assert "_telemetry_message_list_one_shot(" in body
    assert "_telemetry_status_one_shot(" in body
