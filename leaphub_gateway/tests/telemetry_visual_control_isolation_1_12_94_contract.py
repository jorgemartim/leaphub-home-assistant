#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
target = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
target_parts = tuple(int(part) for part in target.split("."))
T = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
C = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")

checks = []
def ok(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)

ok("target-194", target_parts >= (1, 12, 94))
ok("engine-version", f'ENGINE_VERSION = "{target}"' in T)
ok("connector-version", f'CONNECTOR_VERSION = "{target}"' in C)
ok("visual-single-worker", 'thread_name_prefix="leaphub-visual"' in T)
ok("telemetry-no-image", T.count("include_official_image=False") == 2)
ok("state-before-visual", T.index("queued = self._queue_event(") < T.index("self._queue_visual_render("))
ok("offline-helper", "def render_official_visual_snapshot(vehicle_snapshot" in C)
helper = C.split("def render_official_visual_snapshot(", 1)[1].split("def charging_label", 1)[0]
for forbidden in ("LeapmotorApiClient", "operation_password", "client.login", "client.", "handle_command("):
    ok("offline-no-" + forbidden.replace("(", ""), forbidden not in helper)
ok("offline-single-input", "def render_official_visual_snapshot(vehicle_snapshot: dict[str, Any])" in C)
ok("offline-network-false", "allow_network=False" in helper)
ok("debug-explicit-only", "if force_debug_package:" in C)
ok("ack-first", 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windows_open", "windows_close", "sunshade_open", "sunshade_close"}' in C)
ok("safe-retry-only-climate", 'SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}' in C)
ok("c10-off", 'return method(vehicle_id, params={"operate": "off"})' in C)
ok("max-two", "command_attempts < 2" in C)
ok("bounded-reads", "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in T)
ok("precheck-no-global", "COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS = 0.75" in T)
ok("climate-modes", 'numeric_map = {0: "auto", 1: "cooling", 3: "heating"}' in T)
ok("confirmation-fifo", 'thread_name_prefix="leaphub-confirm-arm"' in T)
H193 = (ROOT / "leaphub_gateway" / "tests" / "confirmation_arm_queue_1_12_93_contract.py").read_text(encoding="utf-8")
ok("193-contract-cumulative", 'target_parts >= (1, 12, 93)' in H193 and 'target == "1.12.93"' not in H193)
ok("no-second-client", "_TelemetryOneShotClient" not in T)
print({"ok": True, "checks": len(checks), "version": target})
