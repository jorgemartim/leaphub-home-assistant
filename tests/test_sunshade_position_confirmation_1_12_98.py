from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load("leaphub_connector", APP / "connector.py")
telemetry = load("leaphub_telemetry_sunshade_11298", APP / "telemetry_engine.py")


def bare_engine():
    return object.__new__(telemetry.TelemetryEngine)


def test_physical_sunshade_position_dispatch_is_unchanged_and_never_retried():
    source = (APP / "connector.py").read_text(encoding="utf-8")
    start = source.index('    if command == "sunshade_position":')
    end = source.index('    if command == "set_speed_limit":', start)
    branch = source[start:end]
    assert "native = (percent + 5) // 10" in branch
    assert 'return method(vehicle_id, value=str(native))' in branch
    assert "sunshade_position" not in connector.ACK_FIRST_COMMANDS
    assert "sunshade_position" not in connector.SAFE_STATE_RETRY_COMMANDS


def test_position_uses_fast_confirmation_and_exact_effective_ten_percent_step():
    assert "sunshade_position" in telemetry.TELEMETRY_CONFIRMABLE_COMMANDS
    assert telemetry.CONFIRMATION_SUPERSESSION_FAMILIES["sunshade"] == frozenset({
        "sunshade_open", "sunshade_close", "sunshade_position"
    })
    assert telemetry.TelemetryEngine.COMMAND_CONFIRMATION_FIELDS["sunshade_position"] == ("sunshade_percent",)
    engine = bare_engine()
    context = {"parameters": {"sunshade_position": 45}}
    assert engine._command_confirmation("sunshade_position", {"sunshade_percent": 48}, context) == (False, True)
    assert engine._command_confirmation("sunshade_position", {"sunshade_percent": 50}, context) == (True, True)
    assert engine._command_confirmation("sunshade_position", {"sunshade_percent": 100}, context) == (False, True)
    assert engine._command_confirmation("sunshade_position", {}, context) == (False, False)
    assert engine._command_confirmation("sunshade_position", {"sunshade_percent": 40}, {"parameters": {"sunshade_position": 44}}) == (True, True)


def _db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE command_confirmations (
            confirmation_id TEXT PRIMARY KEY,
            subscription_id TEXT,
            request_id TEXT,
            command_key TEXT,
            command_vehicle_id TEXT,
            status TEXT,
            resolution TEXT,
            resolved_at REAL,
            updated_at TEXT
        )
    """)
    return db


def test_new_percentage_supersedes_old_percentage_but_same_request_is_idempotent():
    engine = bare_engine()
    db = _db()
    db.execute("INSERT INTO command_confirmations VALUES (?,?,?,?,?,'pending',NULL,0,'')", ("old", "sub", "ref_old", "sunshade_position", "car"))
    changed = engine._supersede_pending_confirmations(db, "sub", "sunshade_position", "car", "ref_new", 10.0, "now")
    assert changed == 1
    assert db.execute("SELECT status FROM command_confirmations WHERE confirmation_id='old'").fetchone()[0] == "superseded"

    db.execute("DELETE FROM command_confirmations")
    db.execute("INSERT INTO command_confirmations VALUES (?,?,?,?,?,'pending',NULL,0,'')", ("same", "sub", "ref_same", "sunshade_position", "car"))
    changed = engine._supersede_pending_confirmations(db, "sub", "sunshade_position", "car", "ref_same", 11.0, "now")
    assert changed == 0
    assert db.execute("SELECT status FROM command_confirmations WHERE confirmation_id='same'").fetchone()[0] == "pending"
