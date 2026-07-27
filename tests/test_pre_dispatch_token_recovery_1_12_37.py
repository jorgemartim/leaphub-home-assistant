from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
TELEMETRY = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")

checks = {
    "pre_dispatch_verify_marker": "'remote verify failed'" in CONNECTOR and "'remote verification failed'" in CONNECTOR,
    "invalid_token_marker": "'token is invalid'" in CONNECTOR,
    "post_dispatch_exclusion": "'remote control result failed'" in CONNECTOR and "post_dispatch_result" in CONNECTOR,
    "single_clean_recovery": '"command_recovery"' in TELEMETRY
        and "recovered = connector.handle_command(" in TELEMETRY,
    "recovered_session_is_retained": '"session_retained_for_fast_confirmation"' in TELEMETRY
        and 'recovered["session_reused"] = True' in TELEMETRY,
    "pre_dispatch_recovery_log": "recriando uma única vez antes da ação" in TELEMETRY,
    "version": 'version: "1.12.45"' in (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8"),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("pre-dispatch token recovery contract failed: " + ", ".join(failed))
print({"ok": True, "checks": len(checks), "version": "1.12.45"})
