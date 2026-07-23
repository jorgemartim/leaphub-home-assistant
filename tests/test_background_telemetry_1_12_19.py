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
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_background_test", APP / "telemetry_engine.py")


def new_engine(base: Path, background: bool):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(base)
    return telemetry.TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": "https://example.invalid/telemetry",
            "telemetry_production_enabled": False,
            "telemetry_background_enabled": background,
            "telemetry_background_seconds": 300,
            "telemetry_active_seconds": 20,
            "telemetry_charging_seconds": 25,
            "telemetry_parked_seconds": 90,
            "telemetry_sleep_seconds": 600,
        },
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )


def subscription_payload() -> dict:
    return {
        "subscription_id": "leaphub-staging-account-77",
        "account_id": 77,
        "credentials": {
            "email": "tester@example.invalid",
            "password": "not-a-real-password",
            "certificate_pem": "certificate",
            "private_key_pem": "private-key",
        },
        "vehicle_ids": ["vehicle-1"],
        "enabled": True,
    }


with tempfile.TemporaryDirectory(prefix="leaphub-background-on-") as tmp:
    engine = new_engine(Path(tmp), True)
    payload = subscription_payload()
    assert engine.upsert("staging", payload)["ok"]
    original_collect = engine._collect_with_session
    engine._collect_with_session = lambda *args, **kwargs: {
        "ok": True,
        "vehicles": [{
            "remote_id": "vehicle-1",
            "telemetry": {
                "captured_at": telemetry.utc_iso(),
                "state": "parked",
                "is_parked": True,
                "speed": 0,
            },
        }],
    }
    try:
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET active_until=?,interactive_until=0,command_until=0,"
                "next_run_at=0,status='idle',last_state=NULL WHERE subscription_id=?",
                (time.time() - 60, payload["subscription_id"]),
            )
        due = engine._next_due_subscription()
        assert due is not None, "Assinatura offline não foi selecionada"
        engine._poll_subscription(due)
        with engine.lock, engine._db() as db:
            row = db.execute(
                "SELECT status,last_state,next_run_at FROM subscriptions WHERE subscription_id=?",
                (payload["subscription_id"],),
            ).fetchone()
        assert str(row["status"]) == "active"
        assert str(row["last_state"]) == "parked"
        assert 0 < float(row["next_run_at"]) - time.time() <= 305
        status = engine.status()
        assert status["profiles"]["background_enabled"] is True
        assert status["profiles"]["presence_driven"] is False
        released = engine.release_interactive(payload["subscription_id"])
        assert released["released"] is True
        with engine.lock, engine._db() as db:
            released_row = db.execute(
                "SELECT status,next_run_at FROM subscriptions WHERE subscription_id=?",
                (payload["subscription_id"],),
            ).fetchone()
        assert str(released_row["status"]) == "background"
        assert float(released_row["next_run_at"]) - time.time() <= 305
    finally:
        engine._collect_with_session = original_collect
        if engine._instance_lock_handle is not None:
            engine._instance_lock_handle.close()


with tempfile.TemporaryDirectory(prefix="leaphub-background-off-") as tmp:
    engine = new_engine(Path(tmp), False)
    payload = subscription_payload()
    assert engine.upsert("staging", payload)["ok"]
    with engine.lock, engine._db() as db:
        db.execute(
            "UPDATE subscriptions SET active_until=?,next_run_at=0,status='idle' WHERE subscription_id=?",
            (time.time() - 60, payload["subscription_id"]),
        )
    assert engine._next_due_subscription() is None
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()


print({"ok": True, "checks": 12, "version": "1.12.19"})
