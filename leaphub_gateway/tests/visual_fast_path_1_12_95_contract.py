#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "leaphub_gateway"
target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
target_parts = tuple(int(part) for part in target.split("."))
T = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
C = (APP / "connector.py").read_text(encoding="utf-8")
H194 = (APP / "tests" / "telemetry_visual_control_isolation_1_12_94_contract.py").read_text(encoding="utf-8")

checks = []
def ok(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)

ok("target-195", target_parts >= (1, 12, 95))
ok("versions", f'ENGINE_VERSION = "{target}"' in T and f'CONNECTOR_VERSION = "{target}"' in C)
ok("lazy-class", "class _LazyOfficialImagePackage:" in C)
ok("lazy-loader", "package = _LazyOfficialImagePackage.from_zip(raw)" in C)
ok("no-upstream-eager-loader", "CarImagePackage.from_zip(raw)" not in C)
ok("lazy-observable", "decoded_layer_count" in C)
ok("lossless-fast-method", "IMAGE_WEBP_METHOD = 0" in C)
ok("render-contract-16", "IMAGE_RENDER_CONTRACT_VERSION = 16" in C)
ok("cache-contract-dynamic", 'f"contract-{IMAGE_RENDER_CONTRACT_VERSION}"' in C)
ok("payload-contract-dynamic", '"render_contract_version": IMAGE_RENDER_CONTRACT_VERSION' in C)
ok("two-local-workers", "self.visual_render_workers = 2" in T)
ok("visual-prefix", 'thread_name_prefix="leaphub-visual"' in T)
ok("state-before-image", T.index("queued = self._queue_event(") < T.index("self._queue_visual_render("))
ok("telemetry-no-image", T.count("include_official_image=False") == 2)
ok("offline-render", "def render_official_visual_snapshot(vehicle_snapshot" in C)
helper = C.split("def render_official_visual_snapshot(", 1)[1].split("def charging_label", 1)[0]
for forbidden in ("LeapmotorApiClient", "operation_password", "client.login", "handle_command("):
    ok("offline-no-" + forbidden.replace("(", ""), forbidden not in helper)
ok("offline-network-false", "allow_network=False" in helper)
ok("timing-attribution", "cache_pacote=%s" in C and "camadas_decodificadas=%s" in C)
ok("194-cumulative", "target_parts >= (1, 12, 94)" in H194 and 'ENGINE_VERSION = "1.12.94"' not in H194)
ok("ack-first", 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windows_open", "windows_close", "sunshade_open", "sunshade_close"}' in C)
ok("safe-retry-only-climate", 'SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}' in C)
ok("c10-off", 'return method(vehicle_id, params={"operate": "off"})' in C)
ok("max-two", "command_attempts < 2" in C)
ok("polling-frozen-command", "COMMAND_FIRST_POLL_CEILING_SECONDS = 6" in T)
ok("polling-frozen-interactive", "INTERACTIVE_SECONDS_CEILING = 6" in T)
ok("bounded-reads", "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in T)
ok("precheck-no-global", "COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS = 0.75" in T)
ok("confirmation-fifo", 'thread_name_prefix="leaphub-confirm-arm"' in T)
ok("no-second-client", "_TelemetryOneShotClient" not in T)
print({"ok": True, "checks": len(checks), "version": target})
