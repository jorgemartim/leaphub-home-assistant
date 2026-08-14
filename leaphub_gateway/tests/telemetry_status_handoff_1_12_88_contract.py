from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "leaphub_gateway"
connector = (APP / "connector.py").read_text(encoding="utf-8")
telemetry = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
server = (APP / "connector_server.py").read_text(encoding="utf-8")
checks = []
def check(value, label):
    assert value, label
    checks.append(label)
check('CONNECTOR_VERSION = "1.12.88"' in connector, "connector_version")
check('ENGINE_VERSION = "1.12.88"' in telemetry, "engine_version")
check((APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip() == "1.12.88", "target")
check("_TelemetryOneShotClient" not in telemetry, "no_proxy")
check("def _telemetry_status_one_shot(" in telemetry, "helper")
check('getattr(client, "_get_vehicle_status", None)' in telemetry, "private_status")
check("status_override=status_value" in telemetry, "override_wired")
check("official_leapmotor_client" in telemetry, "real_client_fail_closed")
check("elif official_leapmotor_client:" in telemetry, "real_client_branch")
check("status_override: Any | None = None" in connector, "override_optional")
check('yield_for_manual("antes do refresh")' in telemetry, "yield_before_refresh")
check('yield_for_manual("depois do refresh")' in telemetry, "yield_after_refresh")
check('yield_for_manual("antes da releitura")' in telemetry, "yield_before_retry")
check("não haverá terceira chamada neste ciclo" in telemetry, "no_third")
check("TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in telemetry, "timeout4")
check("allow_slow_network=not (interactive or command_mode)" in telemetry, "no_slow_interactive")
check("include_secondary_network=False" in telemetry, "no_secondary")
check('return method(vehicle_id, params={"operate": "off"})' in connector, "c10_off")
check("repeat_exact_state_command" in connector and "command_attempts < 2" in connector, "max2")
check("self._supersede_pending_confirmations(" in telemetry, "supersession")
check("announce_command_result_async(" in server, "announce")
expected = 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windows_open", "windows_close", "sunshade_open", "sunshade_close"}'
check(expected in connector, "ack_first")
print({"ok": True, "checks": len(checks), "version": "1.12.88"})
