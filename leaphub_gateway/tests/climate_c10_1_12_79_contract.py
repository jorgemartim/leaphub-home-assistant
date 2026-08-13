#!/usr/bin/env python3
"""Static contract for the C10 climate changes in Gateway 1.12.79.

Run from the repository root after applying GATEWAY-1.12.79.patch:
    python3 leaphub_gateway/tests/climate_c10_1_12_79_contract.py
No network or vehicle call is made.
"""
from __future__ import annotations
from pathlib import Path

root = Path(__file__).resolve().parents[2]
connector = (root / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
config = (root / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8")
connector_server = (root / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
telemetry_engine = (root / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
gateway_manager = (root / "leaphub_gateway" / "gateway_manager.py").read_text(encoding="utf-8")
ocpp_gateway = (root / "leaphub_gateway" / "ocpp_gateway.py").read_text(encoding="utf-8")
privacy = (root / "leaphub_gateway" / "privacy.py").read_text(encoding="utf-8")
release_target = (root / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
errors: list[str] = []
checks = 0

def check(value: bool, message: str) -> None:
    global checks
    checks += 1
    if not value:
        errors.append(message)

check('CONNECTOR_VERSION = "1.12.79"' in connector, "connector version != 1.12.79")
check('version: "1.12.79"' in config, "config.yaml version != 1.12.79")
check('VERSION = "1.12.79"' in connector_server, "connector_server version != 1.12.79")
check('ENGINE_VERSION = "1.12.79"' in telemetry_engine, "telemetry_engine version != 1.12.79")
check('VERSION = "1.12.79"' in gateway_manager, "gateway_manager version != 1.12.79")
check('GATEWAY_VERSION = "1.12.79"' in ocpp_gateway, "ocpp_gateway version != 1.12.79")
check('PRIVACY_VERSION = "1.12.79"' in privacy, "privacy version != 1.12.79")
check(release_target == "1.12.79", "RELEASE_TARGET != 1.12.79")
check('"climate_off": "ac_switch"' in connector, "climate_off is not mapped directly to ac_switch")
check('def climate_auto_parameters(' in connector, "AUTO payload helper missing")
for token in (
    '"circle": "in"',
    '"mode": "nohotcold"',
    '"operate": "auto"',
    '"position": "all"',
    '"windlevel": "5"',
    '"wshld": "0"',
):
    check(token in connector, f"AUTO payload missing {token}")
check('return method(vehicle_id, params={"operate": "off"})' in connector, "C10 OFF is not bare ac_switch operate=off")
check('climate_close_parameters(' not in connector, "obsolete operate=close helper still active")
check('"operate": "close"' not in connector, "obsolete operate=close payload still active")

mode_pos = connector.find('def climate_mode_from_status(')
check(mode_pos >= 0, "climate_mode_from_status missing")
mode_block = connector[mode_pos:mode_pos + 4200] if mode_pos >= 0 else ""
pos_switch = mode_block.find('ac_switch')
pos_mode = mode_block.find('attribute(climate, "climate_mode")')
pos_rapid = mode_block.find('rapid_cooling')
check(pos_switch >= 0 and pos_mode >= 0 and pos_switch < pos_mode, "climate_on/off truth does not precede mode")
check('if mode_number == 0:' in mode_block and 'return "auto"' in mode_block, "mode 0 != AUTO")
check('if mode_number == 1:' in mode_block and 'return "cooling"' in mode_block, "mode 1 != cooling")
check('if mode_number == 3:' in mode_block and 'return "heating"' in mode_block, "mode 3 != heating")
check(pos_mode >= 0 and pos_rapid >= 0 and pos_mode < pos_rapid, "rapid flags still override climate_mode")
check('rapid_cooling is True and rapid_heating is not True' in mode_block, "cooling rapid fallback is not conservative")
check('rapid_heating is True and rapid_cooling is not True' in mode_block, "heating rapid fallback is not conservative")

check('"climate_on": "auto"' in connector, "expected AUTO mapping missing")
check('"quick_cool": "cooling"' in connector, "expected cooling mapping missing")
check('"quick_heat": "heating"' in connector, "expected heating mapping missing")
check('expected_mode = expected_climate_mode(command)' in connector, "verification is not mode-aware")
check('mode == expected_mode' in connector, "verification does not compare exact mode")
check('safe_retry_strategy = "repeat_exact_state_command"' in connector, "retry is not exact-state repeat")
check('alternate_mode_close_' not in connector, "obsolete alternate close strategy remains")
check('retry_profile' not in connector, "obsolete retry profile remains")
check('command_attempts < 2' in connector, "two-attempt ceiling missing")

if errors:
    raise SystemExit("Gateway 1.12.79 climate contract FAILED:\n - " + "\n - ".join(errors))
print(f"Gateway 1.12.79 climate contract OK ({checks} checks)")
