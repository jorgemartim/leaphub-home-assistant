from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
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
telemetry = load_module("leaphub_telemetry_verified_upsert_test", APP / "telemetry_engine.py")


def new_engine(base: Path):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(base)
    return telemetry.TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": "https://example.invalid/telemetry",
            "telemetry_production_enabled": False,
        },
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )


def payload(verified: bool = False) -> dict:
    return {
        "subscription_id": "leaphub-staging-account-149",
        "account_id": 149,
        "credentials": {
            "email": "tester@example.invalid",
            "password": "not-a-real-password",
            "certificate_pem": "certificate",
            "private_key_pem": "private-key",
        },
        "vehicle_ids": ["vehicle-149"],
        "enabled": True,
        "credentials_verified": verified,
    }


def test_verified_identical_upsert_preserves_healthy_session():
    with tempfile.TemporaryDirectory(prefix="leaphub-verified-upsert-") as tmp:
        engine = new_engine(Path(tmp))
        sid = payload()["subscription_id"]
        assert engine.upsert("staging", payload())["ok"] is True
        engine.sessions[sid] = {"client": None, "credential_hash": "test"}
        original_close = engine._close_session
        engine._close_session = lambda _sid: (_ for _ in ()).throw(AssertionError("sessão saudável encerrada"))
        try:
            result = engine.upsert("staging", payload(True))
        finally:
            engine._close_session = original_close
            engine.sessions.pop(sid, None)
            if engine._instance_lock_handle is not None:
                engine._instance_lock_handle.close()
        assert result["ok"] is True
        assert result["deduplicated"] is True
        assert result["credentials_verified"] is True
        assert result["session_preserved"] is True
        assert result["auth_reset"] is False
        assert result["cooldown_reset"] is False


def test_verified_upsert_without_session_keeps_recovery_semantics():
    with tempfile.TemporaryDirectory(prefix="leaphub-verified-recovery-") as tmp:
        engine = new_engine(Path(tmp))
        sid = payload()["subscription_id"]
        assert engine.upsert("staging", payload())["ok"] is True
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET status='auth_required',auth_required=1,next_run_at=9999999999 WHERE subscription_id=?",
                (sid,),
            )
        result = engine.upsert("staging", payload(True))
        with engine.lock, engine._db() as db:
            row = db.execute(
                "SELECT status,auth_required FROM subscriptions WHERE subscription_id=?",
                (sid,),
            ).fetchone()
        if engine._instance_lock_handle is not None:
            engine._instance_lock_handle.close()
        assert result["ok"] is True
        assert result["auth_reset"] is True
        assert result["session_preserved"] is False
        assert str(row["status"]) == "waiting"
        assert int(row["auth_required"]) == 0
