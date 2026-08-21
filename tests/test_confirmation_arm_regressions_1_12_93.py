from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
TELEMETRY = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR = (APP / "connector.py").read_text(encoding="utf-8")
SERVER = (APP / "connector_server.py").read_text(encoding="utf-8")


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(name)


def test_execute_command_has_no_synchronous_confirmation_arm_after_dispatch():
    body = function_source(TELEMETRY, "execute_command")
    assert body.count("_queue_command_confirmation_arm(") == 2
    assert "self._arm_command_confirmation(subscription_id, payload, result)" not in body
    assert "self._arm_command_confirmation(subscription_id, payload, recovered)" not in body


def test_async_helpers_are_local_only_and_cannot_dispatch_vehicle_command():
    queue_body = function_source(TELEMETRY, "_queue_command_confirmation_arm")
    worker_body = function_source(TELEMETRY, "_arm_command_confirmation_background")
    combined = queue_body + worker_body
    for forbidden in (
        "handle_command(",
        "execute_vehicle_command(",
        "borrowed_client",
        "_dispatch_timeout(",
        "_create_persistent_session_locked(",
        "client.login(",
        "operation_password",
    ):
        assert forbidden not in combined
    assert "_arm_command_confirmation(" in worker_body


def test_regression_guardrails_for_fast_and_slow_commands_are_unchanged():
    assert 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windshield_defrost", "seat_heat", "seat_ventilation"}' in CONNECTOR
    assert 'return method(vehicle_id, params={"operate": "off"})' in CONNECTOR
    assert "repeat_exact_state_command" in CONNECTOR
    assert "command_attempts < 2" in CONNECTOR
    assert 'numeric_map = {0: "auto", 1: "cooling", 3: "heating"}' in TELEMETRY
    assert "COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS = 0.75" in TELEMETRY
    assert "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in TELEMETRY
    assert "_TelemetryOneShotClient" not in TELEMETRY


def test_trunk_and_sunshade_get_no_new_physical_retry():
    connector_body = function_source(CONNECTOR, "handle_command")
    assert 'SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}' in CONNECTOR
    safe_line = next(line for line in CONNECTOR.splitlines() if line.startswith("SAFE_STATE_RETRY_COMMANDS"))
    assert '"trunk_close"' not in safe_line
    assert '"sunshade_close"' not in safe_line
    assert "command_attempts < 2" in connector_body


def test_server_reports_async_queue_without_changing_result_announcement_order():
    assert "arme_assincrono=%s" in SERVER
    assert 'bool(result.get("confirmation_arm_queued"))' in SERVER
    body = function_source(SERVER, "run_command_job")
    assert body.index("TELEMETRY.execute_command(") < body.index("announce_command_result_async(")
    assert body.index("announce_command_result_async(") < body.index("account_lock.release()")
