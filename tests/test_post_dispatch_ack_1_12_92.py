from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
TELEMETRY = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
SERVER = (APP / "connector_server.py").read_text(encoding="utf-8")
CONNECTOR = (APP / "connector.py").read_text(encoding="utf-8")


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function not found: {name}")


def test_reused_session_does_not_run_auth_success_after_dispatch() -> None:
    body = function_source(TELEMETRY, "execute_command")
    assert 'record_account_auth_success(environment, account_id, "command_session")' not in body
    assert 'record_account_auth_success(environment, account_id, "command_recovery_session")' not in body
    assert 'with self._dispatch_timeout(session["client"]):' in body
    assert "post_dispatch_local_ms" in body
    assert body.index("post_dispatch_local_ms") < body.index("self._queue_command_confirmation_arm(")
    assert "self._arm_command_confirmation(subscription_id, payload, result)" not in body


def test_real_login_still_records_authentication_success() -> None:
    body = function_source(TELEMETRY, "_create_persistent_session_locked")
    assert "client.login()" in body
    assert "self.record_account_auth_success(environment, account_id, origin)" in body
    assert body.index("client.login()") < body.index("self.record_account_auth_success(environment, account_id, origin)")


def test_server_accounts_for_post_dispatch_local_time() -> None:
    assert '"post_dispatch_local_ms": int(phase_latency.get("post_dispatch_local_ms") or 0)' in SERVER
    assert '+ latency["post_dispatch_local_ms"] + latency["confirmation_arm_ms"]' in SERVER
    assert "pos_dispatch_local=%sms" in SERVER


def test_critical_command_guardrails_are_unchanged() -> None:
    assert 'return method(vehicle_id, params={"operate": "off"})' in CONNECTOR
    assert 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windshield_defrost", "seat_heat", "seat_ventilation"}' in CONNECTOR
    assert "repeat_exact_state_command" in CONNECTOR
    assert "command_attempts < 2" in CONNECTOR
