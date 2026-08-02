from __future__ import annotations

import contextlib
import importlib.util
import sys
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CONNECTOR = _load("leaphub_connector", APP / "connector.py")
TELEMETRY = _load("telemetry_session_reuse_test", APP / "telemetry_engine.py")


class _Result:
    def __init__(self, row=None) -> None:
        self._row = row

    def fetchone(self):
        return self._row


class _Database:
    def execute(self, statement, _params=()):
        if str(statement).lstrip().upper().startswith("SELECT"):
            return _Result(
                {
                    "subscription_id": "sub-7",
                    "cooldown_until": 0,
                    "status": "active",
                }
            )
        return _Result()


class _Client:
    def __init__(self) -> None:
        self.login_calls = 0
        self.close_calls = 0

    def login(self) -> None:
        self.login_calls += 1

    def close(self) -> None:
        self.close_calls += 1


def test_command_session_is_reused_by_next_manual_operation() -> None:
    engine = TELEMETRY.TelemetryEngine.__new__(TELEMETRY.TelemetryEngine)
    engine.request_timeout_seconds = 15
    engine.session_max_age_seconds = 3600
    engine.session_idle_seconds = 3600
    engine.lock = threading.RLock()
    engine.session_lock = threading.RLock()
    engine.sessions = {}
    engine.assert_account_cloud_allowed = lambda *_args: None
    engine.begin_account_auth = lambda *_args: {}
    engine.record_account_auth_success = lambda *_args: None
    engine.record_account_auth_failure = lambda *_args, **_kwargs: 60
    engine._db = contextlib.contextmanager(lambda: (yield _Database()))
    engine._session_operation_lock = lambda _sid: contextlib.nullcontext()

    clients: list[_Client] = []
    original_temp = CONNECTOR.secure_temp_directory
    original_create = CONNECTOR.create_client
    original_handle = CONNECTOR.handle_command
    try:
        CONNECTOR.secure_temp_directory = lambda: Path(tempfile.mkdtemp(prefix="leaphub-session-test-"))

        def create_client(*_args, **_kwargs):
            client = _Client()
            clients.append(client)
            return client

        borrowed: list[_Client] = []

        def handle_command(_payload, *, progress=None, borrowed_client=None, borrowed_vehicles=None):
            assert progress is None
            assert borrowed_client is not None
            borrowed.append(borrowed_client)
            return {"ok": True, "status": "confirmation_pending"}

        CONNECTOR.create_client = create_client
        CONNECTOR.handle_command = handle_command
        payload = {
            "account_id": 7,
            "vehicle_id": "vehicle-safe",
            "command": "lock",
            "credentials": {
                "username": "account",
                "password": "secret",
                "operation_password": "pin",
            },
        }

        first = engine.execute_command("staging", payload)
        second = engine.execute_command("staging", payload)

        assert first["status"] == "confirmation_pending"
        assert second["status"] == "confirmation_pending"
        assert first["session_retained_for_fast_confirmation"] is True
        assert second["session_retained_for_fast_confirmation"] is True
        assert len(clients) == 1
        assert clients[0].login_calls == 1
        assert borrowed == [clients[0], clients[0]]
        assert engine.sessions["sub-7"]["client"] is clients[0]
        assert engine.sessions["sub-7"]["credential_hash"]
    finally:
        CONNECTOR.secure_temp_directory = original_temp
        CONNECTOR.create_client = original_create
        CONNECTOR.handle_command = original_handle
        for subscription_id in list(engine.sessions):
            engine._close_session_locked(subscription_id)


def test_engine_contract_marks_fast_confirmation_retention() -> None:
    source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    assert "session_retained_for_fast_confirmation" in source
    assert "cliente autenticado pelo comando" in source
    assert 'ENGINE_VERSION = "1.12.69"' in source
