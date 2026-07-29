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
    spec = importlib.util.spec_from_file_location("ocpp_gateway_user_fairness_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def insert_event(gateway, identity: str, message_id: str, created_offset: float = 0.0) -> int:
    now = time.time() + created_offset
    with gateway.state_db() as db:
        cursor = db.execute(
            "INSERT INTO event_queue(target_name,identity,message_id,ocpp_action,payload_json,attempts,available_at,created_at,last_error) "
            "VALUES('staging',?,?, 'MeterValues','{}',0,?,?,NULL)",
            (identity, message_id, now - 1, now),
        )
        db.commit()
        return int(cursor.lastrowid)


def insert_result(gateway, identity: str, command_id: int, created_offset: float = 0.0) -> int:
    now = time.time() + created_offset
    with gateway.state_db() as db:
        cursor = db.execute(
            "INSERT INTO command_result_queue(target_name,identity,command_id,status,payload_json,error_text,attempts,available_at,created_at,last_error) "
            "VALUES('staging',?,?,'completed','{}','',0,?,?,NULL)",
            (identity, command_id, now - 1, now),
        )
        db.commit()
        return int(cursor.lastrowid)


def configure(gateway):
    target = gateway.ApiTarget("staging", "https://example.invalid/internal/ocpp", "x" * 32)
    gateway.TARGETS_BY_NAME = {"staging": target}
    return target


def test_backlog_from_one_user_does_not_starve_another_user(tmp_path: Path) -> None:
    gateway = load_gateway(tmp_path)
    assert gateway.GATEWAY_VERSION == "1.12.58"
    configure(gateway)
    gateway.remember_queue_owner("staging", "CP-A", 101)
    gateway.remember_queue_owner("staging", "CP-B", 202)

    for index in range(30):
        insert_event(gateway, "CP-A", f"a-{index:02d}", index / 1000)
    insert_event(gateway, "CP-B", "b-00", 1.0)

    delivered: list[str] = []

    def api_call_ok(_target, payload, _timeout):
        delivered.append(str(payload["message_id"]))
        return {}

    gateway.api_call = api_call_ok
    assert gateway.replay_queue_once(3) == 3
    assert delivered[0] == "a-00"
    # User B gets a turn in the first scheduling round even though its row is
    # behind thirty rows from user A in the persistent queue.
    assert delivered[1] == "b-00"
    assert delivered[2] == "a-01"


def test_two_wallboxes_from_same_user_share_one_fair_turn(tmp_path: Path) -> None:
    gateway = load_gateway(tmp_path)
    configure(gateway)
    gateway.remember_queue_owner("staging", "CP-A1", 101)
    gateway.remember_queue_owner("staging", "CP-A2", 101)
    gateway.remember_queue_owner("staging", "CP-B", 202)

    insert_event(gateway, "CP-A1", "a1")
    insert_event(gateway, "CP-A2", "a2", 0.01)
    insert_event(gateway, "CP-B", "b1", 0.02)

    delivered: list[str] = []
    gateway.api_call = lambda _target, payload, _timeout: delivered.append(str(payload["message_id"])) or {}
    assert gateway.replay_queue_once(2) == 2
    assert delivered == ["a1", "b1"]


def test_unknown_owner_falls_back_to_identity_isolation(tmp_path: Path) -> None:
    gateway = load_gateway(tmp_path)
    configure(gateway)
    insert_event(gateway, "OLD-A", "a")
    insert_event(gateway, "OLD-B", "b", 0.01)
    delivered: list[str] = []
    gateway.api_call = lambda _target, payload, _timeout: delivered.append(str(payload["message_id"])) or {}
    assert gateway.replay_queue_once(2) == 2
    assert delivered == ["a", "b"]


def test_command_results_are_fair_between_users(tmp_path: Path) -> None:
    gateway = load_gateway(tmp_path)
    configure(gateway)
    gateway.remember_queue_owner("staging", "CP-A", 101)
    gateway.remember_queue_owner("staging", "CP-B", 202)
    for command_id in range(1, 10):
        insert_result(gateway, "CP-A", command_id, command_id / 1000)
    insert_result(gateway, "CP-B", 900, 1.0)

    delivered: list[tuple[str, int]] = []

    def api_call_ok(_target, payload, _timeout=8.0):
        delivered.append((str(payload["identity"]), int(payload["command_id"])))
        return {}

    gateway.api_call = api_call_ok
    assert gateway.replay_command_results_once(3) == 3
    assert delivered[0] == ("CP-A", 1)
    assert delivered[1] == ("CP-B", 900)
    assert delivered[2] == ("CP-A", 2)


def test_queue_diagnostics_expose_counts_not_owner_ids(tmp_path: Path) -> None:
    gateway = load_gateway(tmp_path)
    configure(gateway)
    gateway.remember_queue_owner("staging", "CP-SECRET", 987654)
    insert_event(gateway, "CP-SECRET", "m1")
    diagnostics = gateway.queue_diagnostics()
    assert diagnostics["fair_replay_enabled"] is True
    assert diagnostics["fairness_scope"] == "owner_user"
    assert diagnostics["owner_scopes"] == 1
    assert diagnostics["largest_owner_event_backlog"] == 1
    assert "987654" not in repr(diagnostics)
    assert "CP-SECRET" not in repr(diagnostics)
