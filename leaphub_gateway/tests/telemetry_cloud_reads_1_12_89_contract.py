from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
telemetry = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
target = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
target_parts = tuple(int(part) for part in target.split("."))

checks = {
    "target_floor_189": target_parts >= (1, 12, 89),
    "engine_matches_target": f'ENGINE_VERSION = "{target}"' in telemetry,
    "vehicle_list_helper": "def _telemetry_vehicle_list_one_shot(" in telemetry,
    "message_list_helper": "def _telemetry_message_list_one_shot(" in telemetry,
    "status_helper_preserved": "def _telemetry_status_one_shot(" in telemetry,
    "private_vehicle_list": 'getattr(client, "_get_vehicle_list", None)' in telemetry,
    "private_message_list": 'getattr(client, "_get_message_list", None)' in telemetry,
    "historical_message_refresh_log": "renovada por refresh durante a leitura de mensagens" in telemetry,
    "manual_before_refresh": 'yield_for_manual("antes do refresh")' in telemetry,
    "manual_after_refresh": 'yield_for_manual("depois do refresh")' in telemetry,
    "no_proxy": "_TelemetryOneShotClient" not in telemetry,
    "no_second_client": "second_client" not in telemetry,
    "four_second_ceiling": "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in telemetry,
    "secondary_network_off": "include_secondary_network=False" in telemetry,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("1.12.89 contract failed: " + ", ".join(failed))

print({"ok": True, "checks": len(checks), "version": target})
