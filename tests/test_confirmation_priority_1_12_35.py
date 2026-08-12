from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_RELEASE_TARGET = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
APP = ROOT / "leaphub_gateway"
server = (APP / "connector_server.py").read_text(encoding="utf-8")
telemetry = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
orchestrator = (APP / "connection_orchestrator.py").read_text(encoding="utf-8")
events = (APP / "event_transport.py").read_text(encoding="utf-8")
build = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")

checks = {
    "version": f'VERSION = "{_RELEASE_TARGET}"' in server and f'ENGINE_VERSION = "{_RELEASE_TARGET}"' in telemetry,
    "active_manual_provider": "def manual_operation_active" in server
        and "manual_active_provider=manual_operation_active" in server,
    "confirmation_ignores_settle_only": "self.manual_active_provider if command_mode else self.manual_pending_provider" in telemetry,
    "command_hint": 'source="command_result"' in server and "EVENT_TRANSPORT.ingest_hint" in server,
    "targeted_vehicle_wake": "vehicle_ids_json" in telemetry and "target_vehicle not in configured" in telemetry,
    "telemetry_metrics": "record_telemetry_cycle" in orchestrator and '"telemetry_latency"' in orchestrator,
    "mqtt_still_off": '"active": False' in events and '"awaiting_homologation"' in events,
    "pipeline_frozen": "Build image first, publish App version last" in build and "matrix:" not in build and '"pytest>=8,<10"' in build,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit(f"failed: {failed}")
print({"ok": True, "checks": len(checks), "version": _RELEASE_TARGET})
