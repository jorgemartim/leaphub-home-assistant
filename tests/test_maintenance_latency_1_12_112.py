"""Gateway 1.12.112-R3 — maintenance incremental e caminho quente preservado."""
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
telemetry = load_module("leaphub_telemetry_1_12_112", APP / "telemetry_engine.py")

CREDENTIALS = {
    "email": "dono@example.invalid",
    "password": "segredo",
    "certificate_pem": "cert",
    "private_key_pem": "key",
}


class Harness:
    def __init__(self, *, queue_max: int = 100000) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="leaphub-112-")
        os.environ["LEAPHUB_TELEMETRY_DIR"] = self.tmp.name
        self.engine = telemetry.TelemetryEngine(
            {
                "telemetry_beta_enabled": True,
                "telemetry_beta_internal_url": "https://example.invalid/api/internal/telemetry/events",
                "telemetry_background_enabled": True,
                "telemetry_queue_max_events": queue_max,
            },
            {"staging": "s" * 32, "production": "p" * 32},
            threading.BoundedSemaphore(4),
        )

    def subscribe(self, sid: str = "sub-112", account_id: int = 1) -> str:
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

    @staticmethod
    def iso(days_ago: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")

    def insert_events(self, sid: str, count: int, *, status: str, old: bool, prefix: str) -> None:
        stamp = self.iso(30 if old else 0)
        rows = []
        for index in range(count):
            event_id = f"{prefix}-{index:07d}"
            delivered = stamp if status == "delivered" else None
            rows.append((
                event_id, sid, "staging", 1, "V1", stamp, b"x", f"hash-{prefix}-{index}", status,
                0, 0.0, None, stamp, delivered, index + 1, f"sem-{prefix}-{index}", 0, "heartbeat",
            ))
        with self.engine._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.executemany(
                    "INSERT INTO events(event_id,subscription_id,environment,account_id,remote_id,source_at,"
                    "payload_encrypted,payload_hash,status,attempts,next_attempt_at,last_error,created_at,delivered_at,"
                    "sequence,semantic_hash,state_changed,event_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

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


def test_versions_and_physical_contracts_are_frozen() -> None:
    release_target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
    assert connector.CONNECTOR_VERSION == release_target
    assert telemetry.ENGINE_VERSION == release_target
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert len(connector.COMMAND_METHODS) == 40
    assert len(connector.EXPERIMENTAL_COMMAND_METHODS) == 12
    assert len(connector.ALL_COMMAND_METHODS) == 52
    assert "windshield_defrost_off" not in connector.ALL_COMMAND_METHODS
    assert tuple(telemetry.TelemetryEngine.COMMAND_POST_DISPATCH_EARLY_CADENCE) == (5, 5, 8)
    assert tuple(telemetry.TelemetryEngine.COMMAND_TRANSIENT_BACKOFF) == (8, 15, 25, 40, 60, 90)
    assert connector.windshield_defrost_parameters()["wshld"] == "2"
    assert connector.windshield_defrost_off_parameters() == {"operate": "off", "wshld": "0"}
    source = inspect.getsource(connector)
    assert 'native = 10 if command == "windows_open" else 0' in source


def test_command_ack_route_is_still_async_and_not_maintenance_coupled() -> None:
    source = (APP / "connector_server.py").read_text(encoding="utf-8")
    assert 'if self.path == "/v1/vehicles/command":' in source
    assert "start_command_job(" in source
    assert '"status": "queued"' in source
    assert '"confirmation_pending": True' in source
    assert "Comando recebido e protegido. Preparando a execução sem bloquear a tela." in source
    # Nenhuma referencia de maintenance deve entrar no servidor HTTP de comando.
    assert "TELEMETRY_MAINTENANCE_DIAG" not in source
    assert "MAINTENANCE_SLICE_BUDGET_SECONDS" not in source


def test_maintenance_source_has_no_unbounded_discovery_pattern() -> None:
    source = inspect.getsource(telemetry.TelemetryEngine._maintenance)
    assert telemetry.MAINTENANCE_STARTUP_GRACE_SECONDS == 180.0
    assert telemetry.MAINTENANCE_INTERVAL_SECONDS == 60.0
    assert telemetry.MAINTENANCE_BUSY_TIMEOUT_SECONDS == 0.15
    assert telemetry.MAINTENANCE_BATCH_SIZE == 200
    assert telemetry.MAINTENANCE_SLICE_BUDGET_SECONDS <= 0.25
    assert telemetry.MAINTENANCE_WRITER_WAIT_SECONDS <= 0.02
    assert telemetry.MAINTENANCE_QUEUE_COUNT_INTERVAL_SECONDS >= 900.0
    assert telemetry.MAINTENANCE_COUNT_BUDGET_SECONDS <= 0.04
    assert "maintenance_rowid" in source
    assert "ORDER BY rowid ASC LIMIT ?" in source
    assert "ORDER BY created_at ASC" not in source
    assert "COALESCE(delivered_at,created_at)" not in source
    assert source.count('SELECT COUNT(*) FROM events') == 1
    assert "MAINTENANCE_QUEUE_COUNT_INTERVAL_SECONDS" in source
    assert "set_progress_handler" in source
    assert "self.lock" not in source
    assert "BEGIN IMMEDIATE" not in source


def test_large_backlog_does_not_turn_limit_200_into_full_scan() -> None:
    # O teste usa backlog bem maior que a fatia e mede apenas a manutencao,
    # nunca rede/veiculo. Em CI/Windows damos margem larga de 1s; a consulta por
    # rowid costuma ficar em poucos ms.
    with Harness(queue_max=100000) as h:
        sid = h.subscribe("backlog-fast")
        h.insert_events(sid, 30000, status="pending", old=False, prefix="recent")
        h.engine._maintenance_queue_count_last_at = time.time()  # isola o scan da fatia
        h.engine._maintenance_last_at = 0.0
        started = time.monotonic()
        result = h.engine._maintenance()
        elapsed = time.monotonic() - started
        assert result == "cleaned"
        assert elapsed < 1.0, elapsed
        assert 0 < h.engine._maintenance_event_cursor <= telemetry.MAINTENANCE_BATCH_SIZE


def test_cleanup_stays_at_most_one_slice_per_pass() -> None:
    with Harness() as h:
        sid = h.subscribe("cleanup-slice")
        total = telemetry.MAINTENANCE_BATCH_SIZE + 50
        h.insert_events(sid, total, status="failed", old=True, prefix="old-failed")
        h.engine._maintenance_queue_count_last_at = time.time()
        h.engine._maintenance_last_at = 0.0
        result = h.engine._maintenance()
        assert result == "cleaned"
        with h.engine._db() as db:
            remaining = int(db.execute("SELECT COUNT(*) FROM events WHERE status='failed'").fetchone()[0])
        assert remaining == 50


def test_internal_writer_busy_makes_maintenance_yield_in_milliseconds() -> None:
    with Harness() as h:
        sid = h.subscribe("writer-yield")
        h.insert_events(sid, 1, status="failed", old=True, prefix="needs-write")
        entered = threading.Event()
        release = threading.Event()

        def blocker() -> None:
            with h.engine.sqlite_writer_lock:
                entered.set()
                release.wait(2.0)

        thread = threading.Thread(target=blocker, daemon=True)
        thread.start()
        assert entered.wait(1.0)
        h.engine._maintenance_queue_count_last_at = time.time()
        h.engine._maintenance_last_at = 0.0
        started = time.monotonic()
        result = h.engine._maintenance()
        elapsed = time.monotonic() - started
        release.set()
        thread.join(timeout=1.0)
        assert result == "writer_busy"
        assert elapsed < 0.30, elapsed
        assert h.engine._maintenance_last_at == 0.0


def test_external_sqlite_writer_still_yields_with_existing_150ms_contract() -> None:
    with Harness() as h:
        sid = h.subscribe("external-writer")
        h.insert_events(sid, 1, status="failed", old=True, prefix="external")
        blocker = sqlite3.connect(h.engine.db_path, timeout=1.0, isolation_level=None)
        blocker.execute("PRAGMA busy_timeout=1000")
        blocker.execute("BEGIN IMMEDIATE")
        try:
            h.engine._maintenance_queue_count_last_at = time.time()
            h.engine._maintenance_last_at = 0.0
            started = time.monotonic()
            try:
                h.engine._maintenance()
            except sqlite3.OperationalError as exc:
                assert "locked" in str(exc).lower() or "busy" in str(exc).lower()
            else:
                raise AssertionError("maintenance deveria ceder ao writer SQLite externo")
            elapsed = time.monotonic() - started
            assert elapsed < 0.8, elapsed
            assert h.engine._maintenance_last_at == 0.0
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()


def test_command_or_confirmation_preempts_cleanup_before_writer() -> None:
    with Harness() as h:
        sid = h.subscribe("command-priority")
        h.insert_events(sid, 3, status="failed", old=True, prefix="priority")
        now = time.time()
        with h.engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET command_until=?,command_started_at=?,command_key=? WHERE subscription_id=?",
                (now + 120.0, now, "climate_on", sid),
            )
        h.engine._maintenance_last_at = 0.0
        result = h.engine._maintenance()
        assert result == "command_priority"
        assert h.engine._maintenance_last_at == 0.0
        with h.engine._db() as db:
            assert int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0]) == 3


def test_count_is_not_executed_every_60_second_pass() -> None:
    with Harness() as h:
        sid = h.subscribe("count-throttle")
        h.insert_events(sid, 1000, status="pending", old=False, prefix="count")
        traces: list[str] = []
        raw = h.engine._connection()
        raw.set_trace_callback(traces.append)
        try:
            h.engine._maintenance_queue_count_last_at = time.time()
            h.engine._maintenance_last_at = 0.0
            assert h.engine._maintenance() == "cleaned"
        finally:
            raw.set_trace_callback(None)
        count_queries = [sql for sql in traces if "SELECT COUNT(*) FROM events" in sql]
        assert not count_queries, count_queries


def test_count_when_due_is_single_and_budgeted() -> None:
    with Harness(queue_max=100000) as h:
        sid = h.subscribe("count-due")
        h.insert_events(sid, 5000, status="pending", old=False, prefix="count-due")
        traces: list[str] = []
        raw = h.engine._connection()
        raw.set_trace_callback(traces.append)
        try:
            h.engine._maintenance_queue_count_last_at = 0.0
            h.engine._maintenance_last_at = 0.0
            started = time.monotonic()
            result = h.engine._maintenance()
            elapsed = time.monotonic() - started
        finally:
            raw.set_trace_callback(None)
        assert result in {"cleaned", "budget"}
        assert elapsed < 1.0, elapsed
        count_queries = [sql for sql in traces if "SELECT COUNT(*) FROM events" in sql]
        assert len(count_queries) <= 1, count_queries
        assert h.engine._maintenance_queue_count_last_at > 0

def test_historical_writer_fixture_does_not_preseed_live_sequence_space() -> None:
    """Carga sintética não pode fabricar duplicatas que o próprio teste condena."""
    path = ROOT / "tests" / "test_sqlite_writer_coordination_1_12_111.py"
    source = path.read_text(encoding="utf-8")
    start = source.index("    def insert_terminal_events(")
    end = source.index("    def close(", start)
    helper = source[start:end]
    assert '0, f"semantic-{index}", 0, "heartbeat",' in helper
    assert 'index + 1, f"semantic-{index}", 0, "heartbeat",' not in helper
    # A proteção real NÃO é afrouxada.
    assert source.count("assert duplicates == 0") == 1
    assert 'WHERE sequence>0 GROUP BY subscription_id,remote_id,sequence HAVING c>1' in source
