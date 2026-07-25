from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
TELEMETRY = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
checks = {
    "steering_methods": '"steering_wheel_heat_on": "steering_wheel_heat_on"' in CONNECTOR and '"steering_wheel_heat_off": "steering_wheel_heat_off"' in CONNECTOR,
    "mirror_methods": '"rearview_mirror_heat_on": "rearview_mirror_heat_on"' in CONNECTOR and '"rearview_mirror_heat_off": "rearview_mirror_heat_off"' in CONNECTOR,
    "capability_names": 'attribute(item, "name")' in CONNECTOR and 'attribute(item, "description")' in CONNECTOR,
    "steering_confirmation": 'steering_wheel_heating' in TELEMETRY,
    "mirror_confirmation": 'left_heating' in TELEMETRY and 'right_heating' in TELEMETRY,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("comfort contract failed: " + ", ".join(failed))
print({"ok": True, "checks": len(checks)})
