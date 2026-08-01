from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "leaphub_gateway" / "ocpp_gateway.py"


def load_gateway(tmp_path: Path):
    os.environ["LEAPHUB_RUNTIME_DIR"] = str(tmp_path)
    os.environ["LEAPHUB_OCPP_STATE_DB"] = str(tmp_path / "ocpp-state.sqlite")
    sys.path.insert(0, str(ROOT / "leaphub_gateway"))
    name = f"ocpp_gateway_delivery_policy_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def insert_event(gateway, identity: str, message_id: str, action: str = "StatusNotification") -> None:
    with gateway.state_db() as db:
        db.execute(
            "INSERT INTO event_queue(target_name,identity,message_id,ocpp_action,payload_json,attempts,available_at,created_at,last_error) "
            "VALUES('staging',?,?,?,?,0,?,?,NULL)",
            (identity, message_id, action, "{}", time.time() - 1, time.time()),
        )
        db.commit()


def test_http_error_classification_is_fail_safe(tmp_path: Path) -> None:
    gateway = load_gateway(tmp_path)
    assert gateway.GATEWAY_VERSION == "1.12.66"

    permanent = gateway.classify_api_error(
        403,
        json.dumps({"temporary": False, "retryable": False, "error_code": "charge_point_not_authorized"}).encode(),
    )
    assert isinstance(permanent, gateway.PermanentApiError)
    assert permanent.status_code == 403
    assert permanent.error_code == "charge_point_not_authorized"

    temporary = gateway.classify_api_error(
        503,
        json.dumps({"temporary": True, "retryable": True, "retry_after_seconds": 17}).encode(),
        "9",
    )
    assert isinstance(temporary, gateway.TransientApiError)
    assert temporary.retry_after_seconds == 17

    rate_limited = gateway.classify_api_error(429, b"{}", "23")
    assert isinstance(rate_limited, gateway.TransientApiError)
    assert rate_limited.retry_after_seconds == 23


def test_permanent_rejection_is_quarantined_and_unblocks_fifo(tmp_path: Path) -> None:
    gateway = load_gateway(tmp_path)
    target = gateway.ApiTarget("staging", "https://example.invalid/internal/ocpp", "secret")
    gateway.TARGETS_BY_NAME = {"staging": target}
    identity = "CP-LIVE-DO-NOT-STORE"
    insert_event(gateway, identity, "m1", "StatusNotification")
    insert_event(gateway, identity, "m2", "MeterValues")

    calls: list[str] = []

    def fake_api(_target, payload, _timeout):
        message_id = str(payload["message_id"])
        calls.append(message_id)
        if message_id == "m1":
            raise gateway.PermanentApiError(
                "HTTP 403: Ponto de carga não autorizado.",
                status_code=403,
                error_code="charge_point_not_authorized",
            )
        return {"ok": True}

    gateway.api_call = fake_api
    assert gateway.replay_queue_once(25) == 1
    assert calls == ["m1", "m2"]

    with gateway.state_db() as db:
        assert db.execute("SELECT COUNT(*) FROM event_queue").fetchone()[0] == 0
        row = db.execute(
            "SELECT identity_hash,message_hash,error_code,occurrences,error_text FROM dead_letter_queue"
        ).fetchone()
    assert row is not None
    assert row[2] == "charge_point_not_authorized"
    assert row[3] == 1
    assert identity not in "|".join(str(value) for value in row)
    assert len(row[0]) == 64
    assert len(row[1]) == 64


def test_transient_rejection_stays_queued_with_backoff(tmp_path: Path) -> None:
    gateway = load_gateway(tmp_path)
    target = gateway.ApiTarget("staging", "https://example.invalid/internal/ocpp", "secret")
    gateway.TARGETS_BY_NAME = {"staging": target}
    insert_event(gateway, "CP-A", "m1", "Heartbeat")

    def fake_api(_target, _payload, _timeout):
        raise gateway.TransientApiError(
            "HTTP 503: temporário",
            status_code=503,
            error_code="temporary_failure",
            retry_after_seconds=31,
        )

    gateway.api_call = fake_api
    before = time.time()
    assert gateway.replay_queue_once(25) == 0
    with gateway.state_db() as db:
        row = db.execute("SELECT attempts,available_at FROM event_queue WHERE message_id='m1'").fetchone()
        dead = db.execute("SELECT COUNT(*) FROM dead_letter_queue").fetchone()[0]
    assert row is not None
    assert row[0] == 1
    assert row[1] >= before + 30
    assert dead == 0


def test_existing_1_12_40_state_database_is_upgraded_additively(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "ocpp-state.sqlite"
    db = sqlite3.connect(db_path)
    db.executescript(
        """
        CREATE TABLE routes (identity TEXT PRIMARY KEY,target_name TEXT NOT NULL,updated_at REAL NOT NULL);
        CREATE TABLE event_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,target_name TEXT NOT NULL,identity TEXT NOT NULL,
            message_id TEXT NOT NULL,ocpp_action TEXT NOT NULL,payload_json TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,available_at REAL NOT NULL,created_at REAL NOT NULL,last_error TEXT NULL,
            UNIQUE(target_name,identity,message_id,ocpp_action)
        );
        CREATE TABLE command_result_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,target_name TEXT NOT NULL,identity TEXT NOT NULL,
            command_id INTEGER NOT NULL,status TEXT NOT NULL,payload_json TEXT NOT NULL,error_text TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,available_at REAL NOT NULL,created_at REAL NOT NULL,last_error TEXT NULL,
            UNIQUE(target_name,identity,command_id)
        );
        """
    )
    now = time.time()
    db.execute("INSERT INTO routes VALUES('CP-EXISTENTE','staging',?)", (now,))
    db.execute(
        "INSERT INTO event_queue(target_name,identity,message_id,ocpp_action,payload_json,available_at,created_at) VALUES(?,?,?,?,?,?,?)",
        ("staging", "CP-EXISTENTE", "old-event", "MeterValues", "{}", now + 300, now),
    )
    db.execute(
        "INSERT INTO command_result_queue(target_name,identity,command_id,status,payload_json,error_text,available_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
        ("staging", "CP-EXISTENTE", 77, "accepted", "{}", "", now + 300, now),
    )
    db.commit()
    db.close()

    gateway = load_gateway(tmp_path)
    with gateway.state_db() as upgraded:
        assert upgraded.execute("SELECT target_name FROM routes WHERE identity='CP-EXISTENTE'").fetchone() == ("staging",)
        assert upgraded.execute("SELECT message_id FROM event_queue WHERE message_id='old-event'").fetchone() == ("old-event",)
        assert upgraded.execute("SELECT command_id FROM command_result_queue WHERE command_id=77").fetchone() == (77,)
        assert upgraded.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dead_letter_queue'").fetchone() == ("dead_letter_queue",)
