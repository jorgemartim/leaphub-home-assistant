"""Gateway 1.12.111-R6 — writer SQLite unico + contratos de throughput preservados."""
from __future__ import annotations

import importlib.util
import inspect
import os
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
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
telemetry = load_module("leaphub_telemetry_1_12_111_r6", APP / "telemetry_engine.py")

CREDENTIALS = {
    "email": "dono@example.invalid",
    "password": "segredo",
    "certificate_pem": "cert",
    "private_key_pem": "key",
}


class Harness:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="leaphub-111-r6-")
        os.environ["LEAPHUB_TELEMETRY_DIR"] = self.tmp.name
        self.engine = telemetry.TelemetryEngine(
            {
                "telemetry_beta_enabled": True,
                "telemetry_beta_internal_url": "https://example.invalid/api/internal/telemetry/events",
                "telemetry_background_enabled": True,
                "telemetry_queue_max_events": 10000,
            },
            {"staging": "s" * 32, "production": "p" * 32},
            threading.BoundedSemaphore(4),
        )

    def subscribe(self, sid: str = "sub-111-r2", account_id: int = 1) -> str:
        result = self.engine.upsert(
            "staging",
            {
                "subscription_id": sid,
                "account_id": account_id,
                "credentials": dict(CREDENTIALS),
                "vehicle_ids": ["V1"],
                "enabled": True,
            },
        )
        assert result["ok"] is True
        return sid

    def subscription(self, sid: str):
        with self.engine._db() as db:
            row = db.execute("SELECT * FROM subscriptions WHERE subscription_id=?", (sid,)).fetchone()
        assert row is not None
        return row

    def old_iso(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")

    def insert_terminal_events(self, sid: str, count: int, status: str = "failed") -> None:
        old = self.old_iso()
        rows = []
        for index in range(count):
            event_id = f"evt-{status}-{index:05d}"
            rows.append((
                event_id, sid, "staging", 1, "V1", old, b"x", f"hash-{index}", status,
                0, 0.0, "old" if status == "failed" else None, old,
                old if status == "delivered" else None,
                0, f"semantic-{index}", 0, "heartbeat",
            ))
        with self.engine._db() as db:
            db.executemany(
                "INSERT INTO events(event_id,subscription_id,environment,account_id,remote_id,source_at,"
                "payload_encrypted,payload_hash,status,attempts,next_attempt_at,last_error,created_at,delivered_at,"
                "sequence,semantic_hash,state_changed,event_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )

    def close(self) -> None:
        pool = getattr(self.engine, "_confirmation_arm_pool", None)
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
            self.engine._confirmation_arm_pool = None
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


def test_versions_and_all_physical_guardrails_stay_frozen() -> None:
    assert tuple(int(x) for x in connector.CONNECTOR_VERSION.split(".")) >= (1, 12, 111)
    assert tuple(int(x) for x in telemetry.ENGINE_VERSION.split(".")) >= (1, 12, 111)
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert tuple(telemetry.TelemetryEngine.COMMAND_POST_DISPATCH_EARLY_CADENCE) == (5, 5, 8)
    assert tuple(telemetry.TelemetryEngine.COMMAND_TRANSIENT_BACKOFF) == (8, 15, 25, 40, 60, 90)
    assert len(connector.COMMAND_METHODS) == 40
    assert len(connector.EXPERIMENTAL_COMMAND_METHODS) == 12
    assert len(connector.ALL_COMMAND_METHODS) == 52
    assert "windshield_defrost_off" not in connector.ALL_COMMAND_METHODS
    on = connector.windshield_defrost_parameters()
    off = connector.windshield_defrost_off_parameters()
    assert on["wshld"] == "2"
    assert off["wshld"] == "0"
    assert {k: v for k, v in on.items() if k != "wshld"} == {k: v for k, v in off.items() if k != "wshld"}
    source = inspect.getsource(connector)
    assert 'native = 10 if command == "windows_open" else 0' in source


def test_db_contextmanager_is_single_and_engine_instantiates() -> None:
    module_source = inspect.getsource(telemetry)
    assert module_source.count("@contextmanager\n    def _db(") == 1
    assert "@contextmanager\n    @contextmanager\n    def _db(" not in module_source
    with Harness() as h:
        with h.engine._db(timeout_seconds=0.25) as db:
            row = db.execute("SELECT 1").fetchone()
        assert row is not None and int(row[0]) == 1


def test_writer_proxy_is_reused_per_thread() -> None:
    """Preserva o contrato 1.12.50/51: o objeto entregue por _db e reutilizado."""
    with Harness() as h:
        with h.engine._db() as first:
            first_id = id(first)
        with h.engine._db() as second:
            assert id(second) == first_id
            assert second is first


def test_maintenance_keeps_historical_60s_throttle_contract() -> None:
    """O novo writer lock elimina a necessidade de alongar o contrato para 300s."""
    with Harness() as h:
        h.engine._maintenance()
        first = h.engine._maintenance_last_at
        assert first > 0
        h.engine._maintenance()
        assert h.engine._maintenance_last_at == first
        forced = time.time() - 120.0
        h.engine._maintenance_last_at = forced
        h.engine._maintenance()
        assert h.engine._maintenance_last_at > forced + 60.0


def test_writer_coordination_is_central_and_reads_stay_outside_it() -> None:
    module_source = inspect.getsource(telemetry)
    db_source = inspect.getsource(telemetry.TelemetryEngine._db)
    assert "class _SQLiteWriterConnection" in module_source
    assert "self.sqlite_writer_lock = threading.RLock()" in module_source
    assert "_SQLiteWriterConnection(db, self.sqlite_writer_lock)" in db_source
    assert "self._writer_connections.get(key)" in db_source
    assert "yield coordinated" in db_source
    assert "abort_writer_transaction" in db_source
    proxy = telemetry._SQLiteWriterConnection
    assert proxy._is_write("UPDATE subscriptions SET status='x'") is True
    assert proxy._is_write("INSERT INTO events(event_id) VALUES ('x')") is True
    assert proxy._is_write("DELETE FROM events") is True
    assert proxy._is_write("SELECT * FROM subscriptions") is False
    assert proxy._is_write("PRAGMA busy_timeout=150") is True
    assert proxy._is_write("PRAGMA journal_mode") is False


def test_maintenance_limits_are_conservative_and_source_is_bounded() -> None:
    assert telemetry.MAINTENANCE_STARTUP_GRACE_SECONDS >= 120
    assert telemetry.MAINTENANCE_INTERVAL_SECONDS == 60.0
    assert telemetry.MAINTENANCE_BUSY_TIMEOUT_SECONDS <= 0.25
    assert 1 <= telemetry.MAINTENANCE_BATCH_SIZE <= 500
    assert telemetry.MAINTENANCE_WORKER_POLL_SECONDS >= 10
    source = inspect.getsource(telemetry.TelemetryEngine._maintenance)
    assert "self.lock" not in source
    assert "BEGIN IMMEDIATE" not in source
    assert "command_priority" in source
    assert "LIMIT ?" in source
    assert "MAINTENANCE_BATCH_SIZE" in source
    assert "DELETE FROM events WHERE status IN ('delivered','failed') AND COALESCE" not in source


def test_maintenance_worker_keeps_110_scheduler_isolation() -> None:
    run_source = inspect.getsource(telemetry.TelemetryEngine._run)
    worker_source = inspect.getsource(telemetry.TelemetryEngine._run_maintenance)
    assert "self._maintenance()" not in run_source
    assert "self._maintenance()" in worker_source
    assert "MAINTENANCE_STARTUP_GRACE_SECONDS" in worker_source
    assert "sqlite_busy" in worker_source
    assert "TELEMETRY_MAINTENANCE_DIAG" in worker_source
    assert "self.schedule_lock" in inspect.getsource(telemetry.TelemetryEngine.boost)
    assert "CONFIRM_SCHED_DIAG" in inspect.getsource(telemetry.TelemetryEngine._next_due_subscription)


def test_pending_command_or_confirmation_preempts_disk_cleanup() -> None:
    with Harness() as h:
        sid = h.subscribe("command-priority")
        h.insert_terminal_events(sid, 3, "failed")
        now = time.time()
        with h.engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET command_until=?,command_started_at=?,command_key=? WHERE subscription_id=?",
                (now + 120.0, now, "climate_on", sid),
            )
        h.engine._maintenance_last_at = 0.0
        result = h.engine._maintenance()
        assert result == "command_priority"
        with h.engine._db() as db:
            count = int(db.execute("SELECT COUNT(*) FROM events WHERE status='failed'").fetchone()[0])
        assert count == 3
        assert h.engine._maintenance_last_at == 0.0


def test_one_cleanup_pass_is_bounded_to_batch_size() -> None:
    with Harness() as h:
        sid = h.subscribe("bounded-cleanup")
        total = int(telemetry.MAINTENANCE_BATCH_SIZE) + 50
        h.insert_terminal_events(sid, total, "failed")
        h.engine._maintenance_last_at = 0.0
        result = h.engine._maintenance()
        assert result == "cleaned"
        with h.engine._db() as db:
            remaining = int(db.execute("SELECT COUNT(*) FROM events WHERE status='failed'").fetchone()[0])
        assert remaining == 50, (remaining, telemetry.MAINTENANCE_BATCH_SIZE)


def test_external_writer_lock_cannot_hold_maintenance_for_seconds() -> None:
    with Harness() as h:
        sid = h.subscribe("writer-lock")
        h.insert_terminal_events(sid, 1, "failed")
        blocker = sqlite3.connect(h.engine.db_path, timeout=1.0, isolation_level=None)
        blocker.execute("PRAGMA busy_timeout=1000")
        blocker.execute("BEGIN IMMEDIATE")
        try:
            h.engine._maintenance_last_at = 0.0
            started = time.monotonic()
            try:
                h.engine._maintenance()
            except sqlite3.OperationalError as exc:
                assert "locked" in str(exc).lower() or "busy" in str(exc).lower()
            else:
                raise AssertionError("maintenance deveria ceder ao writer externo")
            elapsed = time.monotonic() - started
            assert elapsed < 0.8, elapsed
            assert h.engine._maintenance_last_at == 0.0
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()


def test_select_is_not_serialized_behind_internal_writer_lock() -> None:
    with Harness() as h:
        sid = h.subscribe("read-free")
        entered = threading.Event()
        release = threading.Event()

        def writer() -> None:
            with h.engine._db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE subscriptions SET status='writer-test' WHERE subscription_id=?", (sid,))
                entered.set()
                release.wait(2.0)
                db.execute("ROLLBACK")

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        assert entered.wait(1.0)
        started = time.monotonic()
        with h.engine._db(timeout_seconds=0.5) as db:
            row = db.execute("SELECT enabled FROM subscriptions WHERE subscription_id=?", (sid,)).fetchone()
        elapsed = time.monotonic() - started
        release.set()
        thread.join(timeout=1.0)
        assert row is not None
        # WAL + proxy read-only: a leitura nao deve esperar o writer lock de 2s.
        assert elapsed < 0.8, elapsed


def test_parallel_internal_writers_do_not_emit_database_locked() -> None:
    with Harness() as h:
        sid = h.subscribe("parallel-writers")
        subscription = h.subscription(sid)
        h.insert_terminal_events(sid, 20, "failed")
        h.engine._maintenance_last_at = 0.0
        start = threading.Barrier(7)
        errors: list[BaseException] = []
        maintenance_outcomes: list[str] = []

        def capture(fn):
            try:
                start.wait(timeout=2.0)
                fn()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def queue_worker(worker_id: int) -> None:
            for index in range(12):
                vehicle = {
                    "remote_id": "V1",
                    "telemetry": {
                        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "vehicle_state": "parked",
                        "is_parked": True,
                        "test_writer": f"{worker_id}-{index}",
                    },
                }
                result = h.engine._queue_event(
                    subscription,
                    vehicle,
                    vehicle["telemetry"]["captured_at"],
                    "parked",
                    interactive=True,
                    force_delivery=True,
                )
                assert result["queued"] is True

        def boost_worker() -> None:
            for index in range(5):
                result = h.engine.boost(
                    sid,
                    180,
                    "command",
                    {
                        "command_key": "windows_open",
                        "vehicle_remote_id": "V1",
                        "request_id": f"req-r6-{index}",
                        "parameters": {"window_position": 100},
                    },
                )
                assert result["ok"] is True

        def auth_and_schedule_worker() -> None:
            for index in range(12):
                h.engine.record_account_auth_success("staging", 1, origin=f"r6-{index}")
                h.engine._reschedule(sid, 2, "waiting", None, failed=False)

        def maintenance_worker() -> None:
            for _ in range(3):
                h.engine._maintenance_last_at = 0.0
                maintenance_outcomes.append(str(h.engine._maintenance()))

        def delivery_worker() -> None:
            for _ in range(8):
                with h.engine._db() as db:
                    rows = db.execute("SELECT * FROM events WHERE status='failed' LIMIT 2").fetchall()
                if rows:
                    h.engine._delivery_failed(list(rows), "teste local R5")

        threads = [
            threading.Thread(target=capture, args=(lambda: queue_worker(1),), daemon=True),
            threading.Thread(target=capture, args=(lambda: queue_worker(2),), daemon=True),
            threading.Thread(target=capture, args=(lambda: queue_worker(3),), daemon=True),
            threading.Thread(target=capture, args=(boost_worker,), daemon=True),
            threading.Thread(target=capture, args=(auth_and_schedule_worker,), daemon=True),
            threading.Thread(target=capture, args=(maintenance_worker,), daemon=True),
            threading.Thread(target=capture, args=(delivery_worker,), daemon=True),
        ]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=8.0)
        elapsed = time.monotonic() - started
        assert not any(thread.is_alive() for thread in threads), "writer interno ficou bloqueado/deadlock"
        locked = [exc for exc in errors if "locked" in str(exc).lower() or "busy" in str(exc).lower()]
        assert not locked, [str(exc) for exc in locked]
        assert not errors, [f"{type(exc).__name__}: {exc}" for exc in errors]
        assert elapsed < 8.0, elapsed
        assert maintenance_outcomes
        with h.engine._db() as db:
            total = int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            duplicates = int(db.execute(
                "SELECT COUNT(*) FROM (SELECT subscription_id,remote_id,sequence,COUNT(*) c FROM events "
                "WHERE sequence>0 GROUP BY subscription_id,remote_id,sequence HAVING c>1)"
            ).fetchone()[0])
        assert total >= 36
        assert duplicates == 0


def test_window_matcher_and_prepare_defrost_confirmation_are_unchanged() -> None:
    with Harness() as h:
        full_open = {"window_positions": {k: 100 for k in ("front_left", "front_right", "rear_left", "rear_right")}}
        not_open = {"window_positions": {"front_left": 89, "front_right": 100, "rear_left": 100, "rear_right": 100}}
        assert h.engine._command_confirmation("windows_open", full_open, {"parameters": {}}) == (True, True)
        assert h.engine._command_confirmation("windows_open", not_open, {"parameters": {}}) == (False, True)
        assert h.engine._command_confirmation(
            "windshield_defrost",
            {"climate_details": {"windshield_defrost": False}},
            {"parameters": {"enabled": False}},
        ) == (True, True)
        assert "prepare_car" in telemetry.TELEMETRY_CONFIRMABLE_COMMANDS
        assert telemetry.TelemetryEngine.COMMAND_CONFIRMATION_FIELDS["prepare_car"] == (
            "climate_on", "climate_details",
        )
