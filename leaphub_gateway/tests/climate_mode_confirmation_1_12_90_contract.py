from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "leaphub_gateway"
connector = (APP / "connector.py").read_text(encoding="utf-8")
telemetry = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()

checks = {
    "target_floor_190": tuple(int(part) for part in target.split(".")) >= (1, 12, 90),
    "connector_matches_target": f'CONNECTOR_VERSION = "{target}"' in connector,
    "engine_matches_target": f'ENGINE_VERSION = "{target}"' in telemetry,
    "mode_helper": "def _command_climate_mode(" in telemetry,
    "heat_not_switch_only": 'if command in {"climate_on", "quick_cool", "quick_heat"}:' in telemetry,
    "off_switch_generic": 'if command == "climate_off":' in telemetry,
    "expected_heat": '"quick_heat": "heating"' in telemetry,
    "expected_cool": '"quick_cool": "cooling"' in telemetry,
    "expected_auto": '"climate_on": "auto"' in telemetry,
    "numeric_auto": 'numeric_map = {0: "auto", 1: "cooling", 3: "heating"}' in telemetry,
    "future_fail_closed": "return None, False" in telemetry,
    "serialized_alt_signal": '"cooling_and_heating": enum_or_value(attribute(climate, "ac_cooling_and_heating"))' in connector,
    "c10_off_preserved": 'return method(vehicle_id, params={"operate": "off"})' in connector,
    "ack_first_preserved": 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windows_open", "windows_close", "sunshade_open", "sunshade_close"}' in connector,
    "max_two_preserved": "repeat_exact_state_command" in connector and "command_attempts < 2" in connector,
    "no_second_client": "_TelemetryOneShotClient" not in telemetry,
    "bounded_reads_preserved": "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in telemetry,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("1.12.90 contract failed: " + ", ".join(failed))
print({"ok": True, "checks": len(checks), "version": target})
