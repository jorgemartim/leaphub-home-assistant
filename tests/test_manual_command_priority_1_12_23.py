from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8")


def test_manual_settle_window_is_bounded_and_configured() -> None:
    assert 'VERSION = "1.12.23"' in SERVER
    assert 'OPTIONS.get("connector_manual_settle_seconds") or 20' in SERVER
    assert "MANUAL_SETTLE_SECONDS = max(8, min(45," in SERVER
    assert "defer_seconds = MANUAL_SETTLE_SECONDS" in SERVER
    assert "connector_manual_settle_seconds: 20" in CONFIG
    assert 'connector_manual_settle_seconds: "int(8,45)"' in CONFIG


def test_manual_window_is_applied_only_after_journal_finish() -> None:
    finish = SERVER.index("command_journal_finish(request_hash, request_id, result)")
    settle = SERVER.index("defer_seconds = MANUAL_SETTLE_SECONDS", finish)
    release = SERVER.index("account_lock.release()", settle)
    assert finish < settle < release


def test_no_automatic_physical_retry_was_added() -> None:
    start = SERVER.index("command_journal_finish(request_hash, request_id, result)")
    settle = SERVER.index("defer_seconds = MANUAL_SETTLE_SECONDS", start)
    block = SERVER[start:settle]
    assert not re.search(r"execute_command|start_command_job|handle_command", block)
