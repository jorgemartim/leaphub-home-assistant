from __future__ import annotations
import contextlib
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

connector = load("leaphub_connector", APP / "connector.py")

_previous_orchestrator_module = sys.modules.get(
    "leaphub_connection_orchestrator"
)
_previous_event_transport_module = sys.modules.get(
    "leaphub_event_transport"
)

try:
    orch = types.ModuleType("leaphub_connection_orchestrator")
    orch.ORCHESTRATOR = object()
    sys.modules["leaphub_connection_orchestrator"] = orch

    event = types.ModuleType("leaphub_event_transport")
    event.EVENT_TRANSPORT = object()
    sys.modules["leaphub_event_transport"] = event

    telemetry = load(
        "gw188_telemetry",
        APP / "telemetry_engine.py",
    )
finally:
    if _previous_orchestrator_module is None:
        sys.modules.pop("leaphub_connection_orchestrator", None)
    else:
        sys.modules[
            "leaphub_connection_orchestrator"
        ] = _previous_orchestrator_module

    if _previous_event_transport_module is None:
        sys.modules.pop("leaphub_event_transport", None)
    else:
        sys.modules[
            "leaphub_event_transport"
        ] = _previous_event_transport_module

def make_engine():
    engine = telemetry.TelemetryEngine.__new__(telemetry.TelemetryEngine)
    engine._telemetry_request_timeout = lambda _client: contextlib.nullcontext()
    engine.closed = []
    engine._close_session_locked = lambda sid: engine.closed.append(sid)
    return engine

def test_status_one_shot_never_calls_public_retry_wrapper():
    engine = make_engine()
    class Client:
        token = "token"
        def __init__(self):
            self.private_calls = 0
            self.public_calls = 0
        def _get_vehicle_status(self, vehicle):
            self.private_calls += 1
            return {"vehicle": vehicle}
        def get_vehicle_status(self, vehicle):
            self.public_calls += 1
            raise AssertionError("wrapper publico proibido")
    client = Client()
    assert engine._telemetry_status_one_shot("sub", client, "car") == {"vehicle": "car"}
    assert client.private_calls == 1
    assert client.public_calls == 0

def test_manual_command_wins_before_refresh():
    engine = make_engine()
    refreshes = []
    class Client:
        token = "token"
        def _get_vehicle_status(self, _vehicle):
            raise RuntimeError("invalid token: session expired")
    engine._try_refresh_client_session = lambda _client: refreshes.append(1) or True
    decisions = iter((False, True))
    try:
        engine._telemetry_status_one_shot(
            "sub", Client(), "car",
            manual_should_yield=lambda: next(decisions),
        )
    except telemetry.TelemetryYieldForManual:
        pass
    else:
        raise AssertionError("telemetria nao cedeu")
    assert refreshes == []

def test_one_refresh_one_retry():
    engine = make_engine()
    refreshes = []
    class Client:
        token = "token"
        def __init__(self):
            self.calls = 0
        def _get_vehicle_status(self, _vehicle):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("invalid token: session expired")
            return "fresh"
    client = Client()
    engine._try_refresh_client_session = lambda _client: refreshes.append(1) or True
    assert engine._telemetry_status_one_shot("sub", client, "car") == "fresh"
    assert client.calls == 2
    assert refreshes == [1]

def test_no_third_status_after_second_expiry():
    engine = make_engine()
    refreshes = []
    class Client:
        token = "token"
        def __init__(self):
            self.calls = 0
        def _get_vehicle_status(self, _vehicle):
            self.calls += 1
            raise RuntimeError("invalid token: session expired")
    client = Client()
    engine._try_refresh_client_session = lambda _client: refreshes.append(1) or True
    try:
        engine._telemetry_status_one_shot("sub", client, "car")
    except connector.ConnectorSessionExpiredError:
        pass
    else:
        raise AssertionError("segunda expiracao deveria encerrar")
    assert client.calls == 2
    assert refreshes == [1]
    assert engine.closed == ["sub"]

def test_token_guard_does_not_reject_synthetic_private_client_without_token():
    engine = make_engine()

    class SyntheticClient:
        def _get_vehicle_status(self, vehicle):
            return {"synthetic": vehicle}

    assert engine._telemetry_status_one_shot(
        "sub",
        SyntheticClient(),
        "car",
    ) == {"synthetic": "car"}
