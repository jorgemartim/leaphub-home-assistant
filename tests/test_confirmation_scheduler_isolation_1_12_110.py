"""Gateway 1.12.110 — scheduler/confirmacao isolados da trava global."""
from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if "leaphub_connector" not in sys.modules:
    connector = load_module("leaphub_connector", APP / "connector.py")
else:
    connector = sys.modules["leaphub_connector"]
telemetry = load_module("leaphub_telemetry_1_12_110", APP / "telemetry_engine.py")


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


CREDENTIALS = {
    "email": "dono@example.invalid",
    "password": "segredo",
    "certificate_pem": "cert",
    "private_key_pem": "key",
}


class Harness:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="leaphub-110-")
        os.environ["LEAPHUB_TELEMETRY_DIR"] = self.tmp.name
        self.engine = telemetry.TelemetryEngine(
            {
                "telemetry_beta_enabled": True,
                "telemetry_beta_internal_url": "https://example.invalid/api/internal/telemetry/events",
                "telemetry_background_enabled": True,
            },
            {"staging": "s" * 32, "production": "p" * 32},
            threading.BoundedSemaphore(2),
        )

    def subscribe(self, sid: str = "sub-110") -> str:
        result = self.engine.upsert(
            "staging",
            {
                "subscription_id": sid,
                "account_id": 1,
                "credentials": dict(CREDENTIALS),
                "vehicle_ids": ["V1"],
                "enabled": True,
            },
        )
        assert result["ok"] is True
        return sid

    def close(self) -> None:
        self.engine.close_storage()
        handle = getattr(self.engine, "_instance_lock_handle", None)
        if handle is not None:
            handle.close()
        try:
            self.tmp.cleanup()
        except (OSError, PermissionError):
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def hold_lock(lock: threading.RLock, entered: threading.Event, release: threading.Event) -> threading.Thread:
    def runner() -> None:
        with lock:
            entered.set()
            release.wait(3.0)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    assert entered.wait(1.0)
    return thread


def test_versions_and_physical_guardrails() -> None:
    assert version_tuple(connector.CONNECTOR_VERSION) >= (1, 12, 110)
    assert version_tuple(telemetry.ENGINE_VERSION) >= (1, 12, 110)
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert tuple(telemetry.TelemetryEngine.COMMAND_POST_DISPATCH_EARLY_CADENCE) == (5, 5, 8)
    assert tuple(telemetry.TelemetryEngine.COMMAND_TRANSIENT_BACKOFF) == (8, 15, 25, 40, 60, 90)
    assert len(connector.COMMAND_METHODS) == 40
    assert len(connector.EXPERIMENTAL_COMMAND_METHODS) == 12
    assert len(connector.ALL_COMMAND_METHODS) == 52
    assert "windshield_defrost_off" not in connector.ALL_COMMAND_METHODS


def test_defrost_and_window_payload_semantics_are_unchanged() -> None:
    on = connector.windshield_defrost_parameters()
    off = connector.windshield_defrost_off_parameters()
    assert on["wshld"] == "2"
    assert off == {"operate": "off", "wshld": "0"}
    source = inspect.getsource(connector)
    assert 'native = 10 if command == "windows_open" else 0' in source
    assert 'SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}' in source


def test_window_matcher_thresholds_are_unchanged() -> None:
    with Harness() as h:
        full_open = {
            "window_positions": {
                "front_left": 100,
                "front_right": 100,
                "rear_left": 100,
                "rear_right": 100,
            }
        }
        full_closed = {
            "window_positions": {
                "front_left": 0,
                "front_right": 0,
                "rear_left": 0,
                "rear_right": 0,
            }
        }
        almost_open = {
            "window_positions": {
                "front_left": 90,
                "front_right": 90,
                "rear_left": 90,
                "rear_right": 90,
            }
        }
        not_open = {
            "window_positions": {
                "front_left": 89,
                "front_right": 100,
                "rear_left": 100,
                "rear_right": 100,
            }
        }
        assert h.engine._command_confirmation("windows_open", full_open, {"parameters": {}}) == (True, True)
        assert h.engine._command_confirmation("windows_open", almost_open, {"parameters": {}}) == (True, True)
        assert h.engine._command_confirmation("windows_open", not_open, {"parameters": {}}) == (False, True)
        assert h.engine._command_confirmation("windows_close", full_closed, {"parameters": {}}) == (True, True)


def test_confirmation_arm_fifo_is_preserved() -> None:
    with Harness() as h:
        pool = h.engine._confirmation_arm_pool
        assert pool is not None
        assert pool._max_workers == 1


def test_critical_scheduler_methods_do_not_use_global_lock() -> None:
    for name in ("boost", "_next_due_subscription", "_seconds_until_next", "_queue_event", "_maintenance"):
        source = inspect.getsource(getattr(telemetry.TelemetryEngine, name))
        assert "self.lock" not in source, name
    assert "self.schedule_lock" in inspect.getsource(telemetry.TelemetryEngine.boost)
    assert "self.schedule_lock" in inspect.getsource(telemetry.TelemetryEngine._reschedule)
    assert "self.schedule_lock" in inspect.getsource(telemetry.TelemetryEngine._mark_auth_required)


def test_event_queue_keeps_atomic_sqlite_transaction() -> None:
    source = inspect.getsource(telemetry.TelemetryEngine._queue_event)
    assert 'db.execute("BEGIN IMMEDIATE")' in source
    assert 'db.execute("COMMIT")' in source
    assert 'db.execute("ROLLBACK")' in source
    assert "timeout_seconds=5.0" in source


def test_maintenance_is_not_inline_with_confirmation_scheduler() -> None:
    run_source = inspect.getsource(telemetry.TelemetryEngine._run)
    worker_source = inspect.getsource(telemetry.TelemetryEngine._run_maintenance)
    start_source = inspect.getsource(telemetry.TelemetryEngine.start)
    stop_source = inspect.getsource(telemetry.TelemetryEngine.stop)
    assert "self._maintenance()" not in run_source
    assert "self._maintenance()" in worker_source
    assert "TELEMETRY_MAINTENANCE_DIAG" in worker_source
    assert "maintenance_worker" in start_source
    assert "maintenance_worker" in stop_source


def test_scheduler_diagnostic_is_present() -> None:
    source = inspect.getsource(telemetry.TelemetryEngine._next_due_subscription)
    assert "CONFIRM_SCHED_DIAG" in source
    assert "late_ms" in source


def test_boost_does_not_wait_for_unrelated_global_lock() -> None:
    with Harness() as h:
        sid = h.subscribe("boost-global-lock")
        entered = threading.Event()
        release = threading.Event()
        holder = hold_lock(h.engine.lock, entered, release)
        try:
            started = time.monotonic()
            result = h.engine.boost(
                sid,
                180,
                "command",
                {
                    "command_key": "windows_open",
                    "vehicle_remote_id": "V1",
                    "request_id": "req-boost-110",
                    "parameters": {"window_position": 100},
                },
            )
            elapsed = time.monotonic() - started
            assert result["ok"] is True
            # A trava global fica presa por ate 3s no helper. Se boost ainda a
            # usasse, este teste estouraria com folga. 0,8s evita falso negativo
            # em runners Windows lentos sem aceitar a regressao de segundos.
            assert elapsed < 0.8, elapsed
        finally:
            release.set()
            holder.join(timeout=1.0)


def test_next_due_scheduler_does_not_wait_for_unrelated_global_lock() -> None:
    with Harness() as h:
        sid = h.subscribe("due-global-lock")
        now = time.time()
        with h.engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET next_run_at=?,command_until=?,command_started_at=? WHERE subscription_id=?",
                (now - 1.0, now + 120.0, now - 2.0, sid),
            )
        entered = threading.Event()
        release = threading.Event()
        holder = hold_lock(h.engine.lock, entered, release)
        try:
            started = time.monotonic()
            row = h.engine._next_due_subscription()
            elapsed = time.monotonic() - started
            assert row is not None
            assert str(row["subscription_id"]) == sid
            assert elapsed < 0.8, elapsed
        finally:
            release.set()
            holder.join(timeout=1.0)


def test_post_poll_schedule_reconciliation_remains_present() -> None:
    source = inspect.getsource(telemetry.TelemetryEngine._poll_subscription)
    assert "_reconcile_live_post_poll_schedule" in source
    assert "with self.schedule_lock, self._db(timeout_seconds=2.0) as db:" in source


def test_prepare_and_defrost_fast_matchers_remain_present() -> None:
    with Harness() as h:
        assert h.engine._command_confirmation(
            "windshield_defrost",
            {"climate_details": {"windshield_defrost": False}},
            {"parameters": {"enabled": False}},
        ) == (True, True)
        assert "prepare_car" in telemetry.TELEMETRY_CONFIRMABLE_COMMANDS
        assert telemetry.TelemetryEngine.COMMAND_CONFIRMATION_FIELDS["prepare_car"] == (
            "climate_on", "climate_details",
        )
