"""Gateway 1.12.113 — fence mecânico e confirmação terminal sem reenvio."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
CONNECTOR = (APP / "connector.py").read_text(encoding="utf-8")
TELEMETRY = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
SERVER = (APP / "connector_server.py").read_text(encoding="utf-8")


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function not found: {name}")


def ack_first_line() -> str:
    return next(line for line in CONNECTOR.splitlines() if line.startswith("ACK_FIRST_COMMANDS = "))


def test_mechanical_open_close_wait_for_library_remote_result_fence() -> None:
    ack = ack_first_line()
    for command in ("windows_open", "windows_close", "sunshade_open", "sunshade_close"):
        assert f'"{command}"' not in ack
    for command in ("lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close"):
        assert f'"{command}"' in ack
    body = function_source(CONNECTOR, "execute_vehicle_command_ack_first")
    assert "if command not in ACK_FIRST_COMMANDS:" in body
    assert "execute_vehicle_command(" in body
    # Timeout do result/query após write aceito continua ambíguo, não vira retry físico.
    handle = function_source(CONNECTOR, "handle_command")
    assert "is_remote_command_confirmation_timeout" in handle
    assert "cloud_acknowledged_but_result_query_inconclusive" in handle


def test_physical_payloads_and_retry_matrix_are_frozen() -> None:
    assert 'SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}' in CONNECTOR
    assert 'native = 10 if command == "windows_open" else 0' in CONNECTOR
    assert 'params["wshld"] = "0"' in CONNECTOR
    assert '"windshield_defrost_off":' not in CONNECTOR
    assert 'COMMAND_POST_DISPATCH_EARLY_CADENCE = (5, 5, 8)' in TELEMETRY
    assert 'COMMAND_TRANSIENT_BACKOFF = (8, 15, 25, 40, 60, 90)' in TELEMETRY


def test_terminal_unconfirmed_does_not_claim_not_applied() -> None:
    helper_source = function_source(SERVER, "command_confirmation_terminal_payload")
    class DummyConnector:
        CONNECTOR_VERSION = "1.12.113"
    namespace = {
        "Any": object,
        "COMMAND_CONFIRMATION_STATUS_CEILING_SECONDS": 210.0,
        "connector": DummyConnector,
    }
    exec(helper_source, namespace)
    helper = namespace["command_confirmation_terminal_payload"]
    assert helper("sent", {"confirmation_pending": True}, 209.9) is None
    result = helper("sent", {"confirmation_pending": True, "command_dispatched": True, "cloud_accepted": True}, 211.0)
    assert result is not None
    assert result["confirmation_pending"] is False
    assert result["final_outcome"] == "unconfirmed"
    assert result["vehicle_confirmed"] is False
    assert result["not_applied"] is False
    assert result["applied"] is None
    assert result["retry_after_seconds"] == 0


def test_telemetry_exhaustion_announces_terminal_without_physical_action() -> None:
    announce = function_source(TELEMETRY, "_announce_telemetry_unconfirmed_async")
    assert '"command_dispatched": True' in announce
    assert '"cloud_accepted": True' in announce
    assert '"confirmation_pending": False' in announce
    assert '"not_applied": False' in announce
    assert '"final_outcome": "unconfirmed"' in announce
    assert "handle_command" not in announce
    assert "execute_vehicle_command" not in announce
    assert "SAFE_STATE_RETRY_COMMANDS" not in announce
    poll = function_source(TELEMETRY, "_poll_subscription")
    assert "self._announce_telemetry_unconfirmed_async(environment, item)" in poll


def test_window_and_sunshade_confirmation_diagnostics_are_safe_and_visual_remains_real() -> None:
    evaluate = function_source(TELEMETRY, "_evaluate_confirmation")
    assert "CONFIRM_STATE_DIAG" in evaluate
    for forbidden in ("vin", "latitude", "longitude", "password", "token", "certificate"):
        assert forbidden not in evaluate.lower()

    # O visual continua vindo SOMENTE do snapshot real serializado. Não congele
    # uma assinatura textual antiga de build_visual_signature: valide a AST.
    serialize = function_source(CONNECTOR, "serialize_vehicle")
    tree = ast.parse(serialize)
    signature_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_visual_signature"
    ]
    assert len(signature_calls) == 1
    signature_args = [ast.unparse(arg) for arg in signature_calls[0].args]
    assert "window_state" in signature_args
    assert "sunshade_state" in signature_args
    assert '"windows": window_state' in serialize
    assert '"sunshade_open": sunshade_state' in serialize
    assert "optimistic_window" not in CONNECTOR
    assert "optimistic_sunshade" not in CONNECTOR


def test_journal_has_bounded_sent_pending_fallback() -> None:
    assert "COMMAND_CONFIRMATION_STATUS_CEILING_SECONDS = 210.0" in SERVER
    body = function_source(SERVER, "command_journal_status")
    assert "command_confirmation_terminal_payload(status, response, confirmation_age)" in body
    assert "return terminal_unconfirmed" in body
    assert "start_command_job" not in body

def test_maintenance_112_regression_tracks_release_target_without_weakening_physical_guards() -> None:
    source = (ROOT / "tests" / "test_maintenance_latency_1_12_112.py").read_text(encoding="utf-8")
    assert 'assert connector.CONNECTOR_VERSION == "1.12.112"' not in source
    assert 'assert telemetry.ENGINE_VERSION == "1.12.112"' not in source
    assert 'release_target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()' in source
    assert 'assert connector.CONNECTOR_VERSION == release_target' in source
    assert 'assert telemetry.ENGINE_VERSION == release_target' in source
    # Os guardrails fisicos/latencia da 1.12.112 continuam exatamente exigidos.
    assert 'SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}' in source
    assert 'COMMAND_POST_DISPATCH_EARLY_CADENCE) == (5, 5, 8)' in source
    assert 'COMMAND_TRANSIENT_BACKOFF) == (8, 15, 25, 40, 60, 90)' in source
    assert 'native = 10 if command == "windows_open" else 0' in source
