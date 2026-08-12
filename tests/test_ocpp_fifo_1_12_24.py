from __future__ import annotations

import importlib.util
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
    spec = importlib.util.spec_from_file_location("ocpp_gateway_fifo_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def insert_event(gateway, target_name: str, identity: str, message_id: str, action: str, available_at: float) -> int:
    with gateway.state_db() as db:
        cursor = db.execute(
            "INSERT INTO event_queue(target_name,identity,message_id,ocpp_action,payload_json,attempts,available_at,created_at,last_error) "
            "VALUES(?,?,?,?,?,0,?,?,NULL)",
            (target_name, identity, message_id, action, "{}", available_at, time.time()),
        )
        db.commit()
        return int(cursor.lastrowid)


def test_strict_fifo_blocks_overtake_but_not_other_wallboxes(tmp_path: Path) -> None:
    gateway = load_gateway(tmp_path)
    assert gateway.GATEWAY_VERSION == "1.12.75"

    target = gateway.ApiTarget("staging", "https://example.invalid/internal/ocpp", "secret")
    gateway.TARGETS_BY_NAME = {"staging": target}

    now = time.time()
    first = insert_event(gateway, "staging", "CP-A", "m1", "StatusNotification", now + 600)
    second = insert_event(gateway, "staging", "CP-A", "m2", "MeterValues", now - 1)
    insert_event(gateway, "staging", "CP-B", "m3", "Heartbeat", now - 1)
    assert first < second

    delivered: list[str] = []

    def api_call_ok(_target, payload, _timeout):
        delivered.append(str(payload["message_id"]))
        return {}

    gateway.api_call = api_call_ok
    assert gateway.replay_queue_once(25) == 1
    assert delivered == ["m3"]

    with gateway.state_db() as db:
        remaining = db.execute("SELECT message_id FROM event_queue ORDER BY id").fetchall()
    assert remaining == [("m1",), ("m2",)]


def test_failed_first_event_keeps_next_event_behind_it(tmp_path: Path) -> None:
    gateway = load_gateway(tmp_path)
    target = gateway.ApiTarget("staging", "https://example.invalid/internal/ocpp", "secret")
    gateway.TARGETS_BY_NAME = {"staging": target}

    now = time.time()
    insert_event(gateway, "staging", "CP-A", "m1", "StatusNotification", now - 1)
    insert_event(gateway, "staging", "CP-A", "m2", "MeterValues", now - 1)

    attempted: list[str] = []

    def api_call_fail_first(_target, payload, _timeout):
        message_id = str(payload["message_id"])
        attempted.append(message_id)
        if message_id == "m1":
            raise RuntimeError("temporary outage")
        return {}

    gateway.api_call = api_call_fail_first
    assert gateway.replay_queue_once(25) == 0
    assert attempted == ["m1"]

    # Make the first event due again and prove m1 then m2 are delivered in order.
    with gateway.state_db() as db:
        db.execute("UPDATE event_queue SET available_at=? WHERE message_id='m1'", (time.time() - 1,))
        db.commit()

    delivered: list[str] = []

    def api_call_ok(_target, payload, _timeout):
        delivered.append(str(payload["message_id"]))
        return {}

    gateway.api_call = api_call_ok
    assert gateway.replay_queue_once(25) == 2
    assert delivered == ["m1", "m2"]
