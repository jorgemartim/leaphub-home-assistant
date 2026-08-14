from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "leaphub_gateway"
target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
telemetry = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
server = (APP / "connector_server.py").read_text(encoding="utf-8")
connector = (APP / "connector.py").read_text(encoding="utf-8")

tree = ast.parse(telemetry)
funcs = {}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        funcs[node.name] = ast.get_source_segment(telemetry, node) or ""

execute = funcs["execute_command"]
queue = funcs["_queue_command_confirmation_arm"]
worker = funcs["_arm_command_confirmation_background"]
stop = funcs["stop"]

checks = {
    "target_193": target == "1.12.93",
    "versions": all(marker in source for marker, source in (
        (f'ENGINE_VERSION = "{target}"', telemetry),
        (f'VERSION = "{target}"', server),
        (f'CONNECTOR_VERSION = "{target}"', connector),
    )),
    "two_queue_sites": execute.count("_queue_command_confirmation_arm(") == 2,
    "no_sync_normal": "self._arm_command_confirmation(subscription_id, payload, result)" not in execute,
    "no_sync_recovery": "self._arm_command_confirmation(subscription_id, payload, recovered)" not in execute,
    "single_fifo_worker": "max_workers=1" in telemetry and 'thread_name_prefix="leaphub-confirm-arm"' in telemetry,
    "no_forced_cancel": "confirmation_pool.shutdown(wait=True, cancel_futures=False)" in stop,
    "snapshot_parameters": "json.loads(json.dumps(parameters" in queue,
    "queue_has_no_client": all(token not in queue + worker for token in (
        "borrowed_client", "_dispatch_timeout(", "_create_persistent_session_locked(", "client.login(",
    )),
    "background_calls_local_arm": "_arm_command_confirmation(" in worker,
    "background_never_resends": "Nenhum reenvio físico" in queue + worker or "não será repetida" in queue + worker,
    "async_log": "arme_assincrono=%s" in server,
    "precheck_zero": "engine_lock_wait_ms = 0" in execute,
    "bounded_reads": "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in telemetry,
    "mode_aware": 'numeric_map = {0: "auto", 1: "cooling", 3: "heating"}' in telemetry,
    "c10_off": 'return method(vehicle_id, params={"operate": "off"})' in connector,
    "max_two": "repeat_exact_state_command" in connector and "command_attempts < 2" in connector,
    "ack_first": 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windows_open", "windows_close", "sunshade_open", "sunshade_close"}' in connector,
    "no_second_client": "_TelemetryOneShotClient" not in telemetry,
    "image_path_untouched": "official_visual_image_payload(" in connector,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("1.12.93 contract failed: " + ", ".join(failed))
print({"ok": True, "checks": len(checks), "version": target})
