from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "leaphub_gateway"
target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
telemetry = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
server = (APP / "connector_server.py").read_text(encoding="utf-8")
connector = (APP / "connector.py").read_text(encoding="utf-8")

tree = ast.parse(telemetry)
execute = ""
session_create = ""
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "execute_command":
        execute = ast.get_source_segment(telemetry, node) or ""
    if isinstance(node, ast.FunctionDef) and node.name == "_create_persistent_session_locked":
        session_create = ast.get_source_segment(telemetry, node) or ""

checks = {
    "target_floor_192": tuple(int(part) for part in target.split(".")) >= (1, 12, 92),
    "engine_192": f'ENGINE_VERSION = "{target}"' in telemetry,
    "server_192": f'VERSION = "{target}"' in server,
    "connector_192": f'CONNECTOR_VERSION = "{target}"' in connector,
    "no_reused_auth_success": '"command_session"' not in execute,
    "no_recovery_auth_success": '"command_recovery_session"' not in execute,
    "login_success_preserved": "client.login()" in session_create and "self.record_account_auth_success(environment, account_id, origin)" in session_create,
    "post_dispatch_phase": "post_dispatch_local_ms" in execute and "post_dispatch_local_ms" in server,
    "confirmation_not_sync_after_dispatch": "_queue_command_confirmation_arm" in execute and "self._arm_command_confirmation(subscription_id, payload, result)" not in execute,
    "post_dispatch_log": "pos_dispatch_local=%sms" in server,
    "trace_threshold": "TELEMETRY_STAGE_LOG_THRESHOLD_MS = 750" in telemetry,
    "trace_login": '"session_login"' in telemetry,
    "trace_auth_bookkeeping": '"session_auth_success_bookkeeping"' in telemetry,
    "trace_status": '"status_request"' in telemetry,
    "trace_list": '"vehicle_list_request"' in telemetry,
    "trace_messages": '"message_list_request"' in telemetry,
    "trace_serialize": '"serialize_vehicle"' in telemetry,
    "four_second_ceiling": "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in telemetry,
    "precheck_zero_lock": "engine_lock_wait_ms = 0" in execute,
    "precheck_bounded_db": "self._db(timeout_seconds=COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS)" in execute,
    "mode_aware": 'numeric_map = {0: "auto", 1: "cooling", 3: "heating"}' in telemetry,
    "private_reads": all(marker in telemetry for marker in (
        "def _telemetry_vehicle_list_one_shot(",
        "def _telemetry_message_list_one_shot(",
        "def _telemetry_status_one_shot(",
    )),
    "no_second_client": "_TelemetryOneShotClient" not in telemetry,
    "secondary_network_off": "include_secondary_network=False" in telemetry,
    "c10_off": 'return method(vehicle_id, params={"operate": "off"})' in connector,
    "ack_first": 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windows_open", "windows_close", "sunshade_open", "sunshade_close"}' in connector,
    "max_two": "repeat_exact_state_command" in connector and "command_attempts < 2" in connector,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("1.12.92 contract failed: " + ", ".join(failed))
print({"ok": True, "checks": len(checks), "version": target})
