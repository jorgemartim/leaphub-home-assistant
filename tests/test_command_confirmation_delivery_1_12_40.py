from __future__ import annotations

import importlib.util
import os
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


_load("leaphub_connector", APP / "connector.py")
TELEMETRY = _load("telemetry_confirmation_delivery_test", APP / "telemetry_engine.py")


def _engine(base: Path):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(base)
    return TELEMETRY.TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": "https://example.invalid/telemetry",
            "telemetry_production_enabled": False,
            "telemetry_background_enabled": True,
        },
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )


def test_unchanged_confirmation_snapshot_is_delivered() -> None:
    with tempfile.TemporaryDirectory(prefix="leaphub-confirmation-delivery-") as tmp:
        engine = _engine(Path(tmp))
        payload = {
            "subscription_id": "staging-account-7",
            "account_id": 7,
            "credentials": {
                "email": "test@example.invalid",
                "password": "secret",
                "certificate_pem": "certificate",
                "private_key_pem": "private-key",
            },
            "vehicle_ids": ["vehicle-7"],
            "enabled": True,
        }
        assert engine.upsert("staging", payload)["ok"] is True
        vehicle = {
            "remote_id": "vehicle-7",
            "telemetry": {
                "captured_at": TELEMETRY.utc_iso(),
                "state": "parked",
                "is_parked": True,
                "locked": False,
            },
        }
        try:
            with engine.lock, engine._db() as db:
                subscription = db.execute(
                    "SELECT * FROM subscriptions WHERE subscription_id=?",
                    (payload["subscription_id"],),
                ).fetchone()

            first = engine._queue_event(subscription, vehicle, vehicle["telemetry"]["captured_at"], "parked")
            suppressed = engine._queue_event(subscription, vehicle, vehicle["telemetry"]["captured_at"], "parked")
            confirmation = engine._queue_event(
                subscription,
                vehicle,
                vehicle["telemetry"]["captured_at"],
                "parked",
                interactive=True,
                force_delivery=True,
            )

            assert first["queued"] is True
            assert suppressed == {"queued": False, "reason": "unchanged", "sequence": 1}
            assert confirmation["queued"] is True
            assert confirmation["event_kind"] == "confirmation"
            assert confirmation["state_changed"] is False

            with engine.lock, engine._db() as db:
                kinds = [
                    str(row["event_kind"])
                    for row in db.execute(
                        "SELECT event_kind FROM events ORDER BY sequence"
                    ).fetchall()
                ]
            assert kinds == ["change", "confirmation"]
        finally:
            engine.close_storage()
            if engine._instance_lock_handle is not None:
                engine._instance_lock_handle.close()


def test_command_poll_forces_delivery_to_site() -> None:
    source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    assert "force_delivery=command_mode" in source
    assert 'event_kind = "confirmation" if force_delivery' in source
    assert 'ENGINE_VERSION = "1.12.60"' in source
