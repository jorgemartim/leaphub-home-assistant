from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")


def test_status_recovery_is_cooperative_and_bounded() -> None:
    collection = ENGINE[
        ENGINE.index("def _collect_with_session_locked"):
        ENGINE.index("def _close_session_locked")
    ]
    assert "def serialize_status_one_shot(item: Any)" in collection
    assert "client=telemetry_client" in collection
    assert "refreshed = self._try_refresh_client_session(client)" in collection
    assert collection.count("serialized_item = serialize_status_one_shot(item)") == 2
    assert "Operação manual recebeu prioridade após o refresh do status." in collection
    assert "Operação manual aguardando antes da única releitura de status." in collection
    assert "A sessão continuou expirada após um único refresh" in collection


def test_confirmation_reconnect_does_not_keep_old_20_second_gap() -> None:
    assert "delay = 3 if command_mode else 20" in ENGINE
    assert '"confirmacao" if command_mode else "telemetria"' in ENGINE


def test_session_lock_cannot_hold_account_indefinitely() -> None:
    start = ENGINE.index("    def _collect_with_session(")
    end = ENGINE.index("    def _collect_with_session_locked(", start)
    body = ENGINE[start:end]
    assert "TELEMETRY_SESSION_LOCK_WAIT_CEILING_SECONDS" in body
    assert "session_lock.acquire(timeout=0.25)" in body
    assert "manual_should_yield()" in body
    assert "session_lock.release()" in body


def test_command_read_precheck_no_longer_waits_global_engine_lock() -> None:
    start = ENGINE.index("    def execute_command(")
    end = ENGINE.index("    def _collect_with_session(", start)
    body = ENGINE[start:end]
    assert "engine_lock_wait_ms = 0" in body
    assert "self.lock.acquire(timeout=ENGINE_LOCK_COMMAND_TIMEOUT_SECONDS)" not in body
    assert "SELECT subscription_id,cooldown_until,status FROM subscriptions" in body


def test_terminal_worker_failure_is_announced_to_site() -> None:
    assert "def command_journal_fail(request_hash: str | None, request_id: str, exc: BaseException) -> dict[str, Any] | None:" in SERVER
    assert "command_journal_fail(request_hash, request_id, exc)," in SERVER
    assert "announce_command_result_async(" in SERVER
