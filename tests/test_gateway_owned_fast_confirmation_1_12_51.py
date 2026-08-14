from __future__ import annotations

import hashlib
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
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_gateway_owned_fast_test", APP / "telemetry_engine.py")


def new_engine(base: Path):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(base)
    return telemetry.TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": "https://example.invalid/telemetry",
            "telemetry_production_enabled": False,
            "telemetry_background_enabled": True,
        },
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )


def subscription_payload() -> dict:
    return {
        "subscription_id": "leaphub-staging-account-150",
        "account_id": 150,
        "credentials": {
            "email": "tester@example.invalid",
            "password": "not-a-real-password",
            "certificate_pem": "certificate",
            "private_key_pem": "private-key",
        },
        "vehicle_ids": ["vehicle-150"],
        "enabled": True,
    }


def command_payload(request_id: str = "request-fast-confirmation-150") -> dict:
    credentials = dict(subscription_payload()["credentials"])
    credentials["operation_password"] = "123456"
    return {
        "account_id": 150,
        "vehicle_id": "vehicle-150",
        "request_id": request_id,
        "command": "unlock",
        "parameters": {},
        "credentials": credentials,
    }


def wait_for_async_confirmation_arm(engine, timeout: float = 2.0) -> None:
    """Barrier de teste: espera apenas jobs FIFO ja enfileirados pelo Gateway."""
    pool = getattr(engine, "_confirmation_arm_pool", None)
    assert pool is not None
    pool.submit(lambda: None).result(timeout=timeout)


def close_engine(engine) -> None:
    pool = getattr(engine, "_confirmation_arm_pool", None)
    engine._confirmation_arm_pool = None
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=False)
    engine.sessions.clear()
    engine.close_storage()
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()


def test_command_completion_arms_fast_without_site_poll() -> None:
    with tempfile.TemporaryDirectory(prefix="leaphub-gateway-fast-") as tmp:
        engine = new_engine(Path(tmp))
        payload = subscription_payload()
        sid = payload["subscription_id"]
        assert engine.upsert("staging", payload)["ok"] is True
        credential_hash = hashlib.sha256(
            telemetry.canonical_json(payload["credentials"])
        ).hexdigest()
        engine.sessions[sid] = {
            "client": object(),
            "temp_dir": tmp,
            "credential_hash": credential_hash,
            "created_at": time.time(),
            "last_used_at": time.time(),
            "vehicles": [],
        }
        original_handle = connector.handle_command
        original_auth_success = engine.record_account_auth_success
        connector.handle_command = lambda *_args, **_kwargs: {
            "ok": True,
            "accepted": True,
            "command_dispatched": True,
            "cloud_accepted": True,
            "confirmation_pending": True,
        }
        engine.record_account_auth_success = lambda *_args, **_kwargs: None
        try:
            result = engine.execute_command("staging", command_payload())
            wait_for_async_confirmation_arm(engine)
            with engine.lock, engine._db() as db:
                row = db.execute(
                    "SELECT command_key,command_vehicle_id,command_context_json,"
                    "command_poll_count,command_started_at,command_until,next_run_at "
                    "FROM subscriptions WHERE subscription_id=?",
                    (sid,),
                ).fetchone()
        finally:
            connector.handle_command = original_handle
            engine.record_account_auth_success = original_auth_success
            close_engine(engine)

        assert result["confirmation_armed_by_gateway"] is True
        assert str(row["command_key"]) == "unlock"
        assert str(row["command_vehicle_id"]) == "vehicle-150"
        assert "request-fast-confirmation-150" in str(row["command_context_json"])
        assert int(row["command_poll_count"]) == 0
        assert float(row["command_started_at"]) > 0
        assert float(row["command_until"]) > time.time()
        assert float(row["next_run_at"]) <= time.time() + 1


def test_same_request_boost_preserves_existing_confirmation_progress() -> None:
    with tempfile.TemporaryDirectory(prefix="leaphub-gateway-fast-idempotent-") as tmp:
        engine = new_engine(Path(tmp))
        payload = subscription_payload()
        sid = payload["subscription_id"]
        assert engine.upsert("staging", payload)["ok"] is True
        context = {
            "command_key": "unlock",
            "vehicle_remote_id": "vehicle-150",
            "request_id": "request-fast-confirmation-150",
            "parameters": {},
        }
        first = engine.boost(sid, 90, "command", context)
        assert first["ok"] is True
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET command_poll_count=2 WHERE subscription_id=?",
                (sid,),
            )
            before = db.execute(
                "SELECT command_started_at,command_until FROM subscriptions WHERE subscription_id=?",
                (sid,),
            ).fetchone()
        time.sleep(0.01)
        repeated = engine.boost(sid, 180, "command", context)
        with engine.lock, engine._db() as db:
            after = db.execute(
                "SELECT command_poll_count,command_started_at,command_until FROM subscriptions WHERE subscription_id=?",
                (sid,),
            ).fetchone()
        close_engine(engine)

        assert repeated["ok"] is True
        assert repeated["confirmation_window_reused"] is True
        assert int(after["command_poll_count"]) == 2
        assert float(after["command_started_at"]) == float(before["command_started_at"])
        assert float(after["command_until"]) >= float(before["command_until"])


def test_protected_recovery_keeps_new_command_context() -> None:
    with tempfile.TemporaryDirectory(prefix="leaphub-gateway-fast-recovery-") as tmp:
        engine = new_engine(Path(tmp))
        payload = subscription_payload()
        sid = payload["subscription_id"]
        assert engine.upsert("staging", payload)["ok"] is True
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET status='recovering',next_run_at=? WHERE subscription_id=?",
                (time.time() + 30, sid),
            )
        result = engine.boost(
            sid,
            180,
            "command",
            {
                "command_key": "unlock",
                "vehicle_remote_id": "vehicle-150",
                "request_id": "request-fast-recovery-150",
                "parameters": {},
            },
        )
        with engine.lock, engine._db() as db:
            row = db.execute(
                "SELECT status,command_key,command_vehicle_id,command_context_json,"
                "command_started_at,command_until FROM subscriptions WHERE subscription_id=?",
                (sid,),
            ).fetchone()
        close_engine(engine)

        assert result["ok"] is True
        assert result["protected_wait"] is True
        assert str(row["status"]) == "recovering"
        assert str(row["command_key"]) == "unlock"
        assert str(row["command_vehicle_id"]) == "vehicle-150"
        assert "request-fast-recovery-150" in str(row["command_context_json"])
        assert float(row["command_started_at"]) > 0
        assert float(row["command_until"]) > time.time()
