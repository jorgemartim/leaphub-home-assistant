"""Gateway 1.12.108 — regressões da agenda FAST e das proteções concorrentes."""
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
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if "leaphub_connector" not in sys.modules:
    connector = load_module("leaphub_connector", APP / "connector.py")
else:
    connector = sys.modules["leaphub_connector"]
telemetry = load_module("leaphub_telemetry_fast_arm_1_12_108", APP / "telemetry_engine.py")

CREDENTIALS = {
    "email": "dono@example.invalid",
    "password": "segredo",
    "certificate_pem": "cert",
    "private_key_pem": "key",
}


class Harness:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="leaphub-fast-arm-108-")
        os.environ["LEAPHUB_TELEMETRY_DIR"] = self.tmp.name
        self.engine = telemetry.TelemetryEngine(
            {
                "telemetry_beta_enabled": True,
                "telemetry_beta_internal_url": "https://example.invalid/telemetry",
                "telemetry_background_enabled": True,
            },
            {"staging": "s" * 32, "production": "p" * 32},
            threading.BoundedSemaphore(2),
        )

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

    def subscribe(self, sid: str = "sub-108") -> str:
        self.engine.upsert(
            "staging",
            {
                "subscription_id": sid,
                "account_id": 1,
                "credentials": dict(CREDENTIALS),
                "vehicle_ids": ["V1"],
                "enabled": True,
            },
        )
        with self.engine.lock, self.engine._db() as db:
            now = time.time()
            db.execute(
                "UPDATE subscriptions SET status='active',active_until=?,interactive_until=0,command_until=0,"
                "command_key=NULL,command_vehicle_id=NULL,command_context_json=NULL,command_poll_count=0,"
                "command_started_at=0,next_run_at=? WHERE subscription_id=?",
                (now + 900, now - 1, sid),
            )
        return sid

    def row(self, sid: str):
        with self.engine.lock, self.engine._db() as db:
            return db.execute("SELECT * FROM subscriptions WHERE subscription_id=?", (sid,)).fetchone()

    def pending(self, sid: str) -> int:
        with self.engine.lock, self.engine._db() as db:
            return int(db.execute(
                "SELECT COUNT(*) FROM command_confirmations WHERE subscription_id=? AND status='pending'",
                (sid,),
            ).fetchone()[0])


def command_context(request_id: str = "req-108") -> dict[str, object]:
    return {
        "command_key": "unlock",
        "vehicle_remote_id": "V1",
        "request_id": request_id,
        "parameters": {},
    }


def test_release_and_physical_guardrails_are_unchanged() -> None:
    assert telemetry.ENGINE_VERSION == "1.12.108"
    assert connector.CONNECTOR_VERSION == "1.12.108"
    assert tuple(telemetry.TelemetryEngine.COMMAND_POST_DISPATCH_EARLY_CADENCE) == (5, 5, 8)
    assert tuple(telemetry.TelemetryEngine.COMMAND_TRANSIENT_BACKOFF) == (8, 15, 25, 40, 60, 90)
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert "windshield_defrost" not in connector.SAFE_STATE_RETRY_COMMANDS
    assert "windshield_defrost" not in connector.ACK_FIRST_COMMANDS
    assert connector.windshield_defrost_parameters()["wshld"] == "2"
    assert connector.climate_auto_parameters({"target_temperature": 24})["wshld"] == "0"


def test_command_cuts_soft_recovery_wait_but_interactive_does_not() -> None:
    for status in ("recovering", "error"):
        with Harness() as h:
            sid = h.subscribe("soft-" + status)
            before = time.time()
            with h.engine.lock, h.engine._db() as db:
                db.execute(
                    "UPDATE subscriptions SET status=?,next_run_at=?,consecutive_failures=1 WHERE subscription_id=?",
                    (status, before + 50, sid),
                )
            result = h.engine.boost(sid, seconds=180, profile="command", context=command_context("req-" + status))
            row = h.row(sid)
            assert result["ok"] is True
            assert result.get("protected_wait") is not True
            assert float(row["next_run_at"]) <= time.time() + 2.0
            assert float(row["command_until"]) > time.time()
            assert h.pending(sid) == 1

    with Harness() as h:
        sid = h.subscribe("interactive-recovery")
        before = time.time()
        with h.engine.lock, h.engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET status='recovering',next_run_at=? WHERE subscription_id=?",
                (before + 50, sid),
            )
        result = h.engine.boost(sid, seconds=300, profile="interactive", context={})
        row = h.row(sid)
        assert result["ok"] is True
        assert result["protected_wait"] is True
        assert float(row["next_run_at"]) > before + 40
        assert h.pending(sid) == 0


def test_cooldown_and_auth_are_never_bypassed_by_command_boost() -> None:
    with Harness() as h:
        sid = h.subscribe("cooldown-hard")
        h.engine._apply_account_subscription_cooldown("staging", 1, 300, "teste", "rate_limit")
        result = h.engine.boost(sid, seconds=180, profile="command", context=command_context("req-cooldown"))
        row = h.row(sid)
        assert result["ok"] is False
        assert result["cooldown"] is True
        assert float(row["cooldown_until"]) > time.time() + 200
        assert h.pending(sid) == 0

    with Harness() as h:
        sid = h.subscribe("auth-hard")
        h.engine._mark_auth_required(sid, "teste")
        result = h.engine.boost(sid, seconds=180, profile="command", context=command_context("req-auth"))
        row = h.row(sid)
        assert result["ok"] is False
        assert result["auth_required"] is True
        assert int(row["auth_required"]) == 1
        assert h.pending(sid) == 0


def _run_stale_success_poll_with_interleave(h: Harness, sid: str, interleave) -> None:
    engine = h.engine
    with engine.lock, engine._db() as db:
        snapshot = db.execute("SELECT * FROM subscriptions WHERE subscription_id=?", (sid,)).fetchone()
    assert snapshot is not None

    def fake_collect(*_args, **_kwargs):
        return {
            "ok": True,
            "collection_profile": "fast",
            "vehicles": [{
                "remote_id": "V1",
                "telemetry": {
                    "captured_at": telemetry.utc_iso(),
                    "vehicle_state": "parked",
                    "is_parked": True,
                    "locked": True,
                },
            }],
        }

    after_network = threading.Event()
    allow_finalize = threading.Event()

    def block_queue(*_args, **_kwargs):
        after_network.set()
        assert allow_finalize.wait(4), "teste não liberou finalização"
        return {"queued": False, "reason": "test"}

    engine._collect_with_session = fake_collect
    engine._queue_event = block_queue
    engine._queue_visual_render = lambda *_args, **_kwargs: False

    thread_errors: list[BaseException] = []

    def run_poll() -> None:
        try:
            engine._poll_subscription(snapshot)
        except BaseException as exc:  # pragma: no cover - propagado pela asserção abaixo
            thread_errors.append(exc)

    thread = threading.Thread(target=run_poll, daemon=True)
    thread.start()
    assert after_network.wait(3), "poll não chegou à fase local pós-rede"
    interleave()
    allow_finalize.set()
    thread.join(5)
    assert not thread.is_alive(), "poll ficou preso"
    assert not thread_errors, f"poll falhou durante o teste concorrente: {thread_errors!r}"


def test_stale_poll_cannot_overwrite_new_fast_arm_or_poll_counter() -> None:
    with Harness() as h:
        sid = h.subscribe("race-fast")

        def arm_new_command() -> None:
            result = h.engine.boost(
                sid,
                seconds=180,
                profile="command",
                context=command_context("req-race-fast"),
            )
            assert result["ok"] is True
            assert h.pending(sid) == 1

        _run_stale_success_poll_with_interleave(h, sid, arm_new_command)
        row = h.row(sid)
        assert float(row["command_until"]) > time.time()
        assert int(row["command_poll_count"] or 0) == 0, (
            "poll antigo consumiu/reescreveu o contador da confirmação que nasceu depois dele"
        )
        assert float(row["next_run_at"]) <= time.time() + 2.0, (
            "poll antigo sobrescreveu o arme imediato com a cadência normal"
        )
        assert h.pending(sid) == 1


def test_stale_success_poll_cannot_erase_new_cooldown() -> None:
    with Harness() as h:
        sid = h.subscribe("race-cooldown")

        def add_cooldown() -> None:
            h.engine._apply_account_subscription_cooldown(
                "staging", 1, 300, "rate limit concorrente", "rate_limit"
            )

        _run_stale_success_poll_with_interleave(h, sid, add_cooldown)
        row = h.row(sid)
        assert str(row["status"]) == "cooldown"
        assert float(row["cooldown_until"]) > time.time() + 200
        assert float(row["next_run_at"]) > time.time() + 200


def test_source_wires_reconciliation_into_success_finalizer() -> None:
    source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    poll = source[source.index("    def _poll_subscription("):]
    poll = poll[: poll.index("    def _queue_visual_render(")]
    assert "_reconcile_live_post_poll_schedule(" in poll
    assert "if hard_live_protection:" in poll
    assert "elif clear_command:" in poll
    # O conserto não pode virar min(next_run) incondicional: um next_run antigo
    # já vencido causaria laço apertado. A preservação exige comando MAIS NOVO.
    helper = source[source.index("    def _reconcile_live_post_poll_schedule("):]
    helper = helper[: helper.index("    def _poll_subscription(")]
    assert "newer_command_armed" in helper
    assert "newest_started_at > snapshot_started_at" in helper
    assert "if newer_command_armed and not hard_protection:" in helper
