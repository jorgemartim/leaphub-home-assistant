from __future__ import annotations

import importlib.util
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
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_storage_throughput_test", APP / "telemetry_engine.py")


def new_engine(base: Path, options: dict | None = None):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(base)
    merged = {
        "telemetry_beta_enabled": True,
        "telemetry_beta_internal_url": "https://example.invalid/telemetry",
        "telemetry_production_enabled": False,
    }
    merged.update(options or {})
    return telemetry.TelemetryEngine(
        merged,
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(4),
    )


def close_engine(engine) -> None:
    engine.close_storage()
    engine.close_storage()
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()


def payload(account: int = 150) -> dict:
    return {
        "subscription_id": f"leaphub-staging-account-{account}",
        "account_id": account,
        "credentials": {
            "email": f"tester{account}@example.invalid",
            "password": "not-a-real-password",
            "certificate_pem": "certificate",
            "private_key_pem": "private-key",
        },
        "vehicle_ids": [f"vehicle-{account}"],
        "enabled": True,
    }


def test_queue_uses_wal_without_touching_data():
    """WAL é o modo preferido e nenhuma assinatura é perdida na migração."""
    with tempfile.TemporaryDirectory(prefix="leaphub-wal-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            assert engine.upsert("staging", payload())["ok"] is True
            with engine.lock, engine._db() as db:
                mode = str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                synchronous = int(db.execute("PRAGMA synchronous").fetchone()[0])
                total = int(db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0])
            assert mode in {"wal", "delete"}, mode
            assert total == 1
            if mode == "wal":
                assert engine.storage_journal_mode == "wal"
                assert synchronous == 1  # NORMAL
            else:
                assert synchronous == 2  # FULL, fallback preservado
        finally:
            close_engine(engine)


def test_connection_is_reused_per_thread():
    with tempfile.TemporaryDirectory(prefix="leaphub-conn-reuse-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            with engine._db() as first:
                first_id = id(first)
            with engine._db() as second:
                assert id(second) == first_id
        finally:
            close_engine(engine)


def test_maintenance_is_throttled():
    with tempfile.TemporaryDirectory(prefix="leaphub-maintenance-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            engine._maintenance()
            first = engine._maintenance_last_at
            assert first > 0
            engine._maintenance()
            assert engine._maintenance_last_at == first
            # Vencida a janela, a manutenção volta a rodar e remarca o relógio.
            # A comparação é contra o valor forçado, não contra `first`: em
            # plataformas com time.time() de baixa resolução os dois podem
            # cair no mesmo tique e o teste piscaria sem motivo.
            forced = time.time() - 120.0
            engine._maintenance_last_at = forced
            engine._maintenance()
            assert engine._maintenance_last_at > forced + 60.0
        finally:
            close_engine(engine)


def test_maintenance_throttle_never_delays_session_expiry():
    """O throttle vale só para a retenção da fila, nunca para a sessão.

    Regressão de 1.12.50: a primeira versão do throttle saía do método antes da
    varredura de sessões, e uma sessão realmente inativa deixava de ser
    descartada enquanto a janela de um minuto não vencesse.
    """
    with tempfile.TemporaryDirectory(prefix="leaphub-idle-session-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            closed = {"count": 0}

            class _Client:
                def close(self) -> None:
                    closed["count"] += 1

            sid = "leaphub-staging-account-150"
            engine.sessions[sid] = {
                "client": _Client(),
                "temp_dir": None,
                "credential_hash": "hash",
                "created_at": time.time(),
                "last_used_at": time.time(),
            }
            # Consome a janela do throttle com uma manutenção recente.
            engine._maintenance()
            assert sid in engine.sessions

            # Mesma janela, mas agora a sessão está inativa de verdade.
            engine.sessions[sid]["last_used_at"] = time.time() - (engine.session_idle_seconds + 60)
            engine._maintenance()
            assert sid not in engine.sessions
            assert closed["count"] == 1
        finally:
            close_engine(engine)


def test_delivery_backoff_stays_under_two_minutes():
    """Uma lentidão da hospedagem não pode calar a telemetria por meia hora."""
    with tempfile.TemporaryDirectory(prefix="leaphub-backoff-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            assert engine.upsert("staging", payload())["ok"] is True
            now = time.time()
            with engine.lock, engine._db() as db:
                db.execute(
                    "INSERT INTO events(event_id,subscription_id,environment,account_id,remote_id,source_at,"
                    "payload_encrypted,payload_hash,status,attempts,next_attempt_at,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,'pending',?,?,?)",
                    (
                        "e" * 64,
                        payload()["subscription_id"],
                        "staging",
                        150,
                        "vehicle-150",
                        telemetry.utc_iso(),
                        engine.fernet.encrypt(b"{}"),
                        "h" * 64,
                        20,
                        now,
                        telemetry.utc_iso(),
                    ),
                )
                rows = db.execute("SELECT * FROM events WHERE status='pending'").fetchall()
            engine._delivery_failed(rows, "hospedagem lenta")
            with engine.lock, engine._db() as db:
                row = db.execute("SELECT attempts,next_attempt_at FROM events WHERE event_id=?", ("e" * 64,)).fetchone()
            assert int(row["attempts"]) == 21
            # Mesmo com muitas tentativas o teto permanece em ~2 minutos.
            assert float(row["next_attempt_at"]) - now <= 126.0
        finally:
            close_engine(engine)


def test_scheduler_does_not_dispatch_the_same_subscription_twice():
    with tempfile.TemporaryDirectory(prefix="leaphub-inflight-") as tmp:
        engine = new_engine(Path(tmp), {"telemetry_poll_workers": 2})
        try:
            assert engine.upsert("staging", payload())["ok"] is True
            sid = payload()["subscription_id"]
            with engine.lock, engine._db() as db:
                db.execute("UPDATE subscriptions SET next_run_at=? WHERE subscription_id=?", (0.0, sid))
            assert engine.poll_workers == 2
            first = engine._next_due_subscription()
            assert first is not None and str(first["subscription_id"]) == sid
            engine._inflight.add(sid)
            assert engine._next_due_subscription() is None
            engine._inflight.discard(sid)
            assert engine._next_due_subscription() is not None
        finally:
            close_engine(engine)


def test_command_latency_exposes_session_phases():
    """As fases que antes ficavam invisíveis precisam chegar ao resultado."""
    source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    assert 'phase["session_wait_ms"] = session_wait_ms' in source
    assert 'phase["session_login_ms"] = session_login_ms' in source
    server = (APP / "connector_server.py").read_text(encoding="utf-8")
    assert '"session_wait_ms": int(phase_latency.get("session_wait_ms") or 0)' in server
    assert '"session_login_ms": int(phase_latency.get("session_login_ms") or 0)' in server
    assert '"unaccounted_ms": max(0, latency["remote_execute_ms"]' in server


def test_library_version_is_resolved_once():
    connector._PACKAGE_VERSION_CACHED = False
    connector._PACKAGE_VERSION_VALUE = None
    calls = {"count": 0}
    original = connector.version

    def counting_version(name: str):
        calls["count"] += 1
        return original(name)

    connector.version = counting_version
    try:
        connector.package_version()
        connector.package_version()
        connector.package_version()
    finally:
        connector.version = original
    assert calls["count"] <= 1
