from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))

spec = importlib.util.spec_from_file_location("leaphub_connector_hotfix_112106", APP / "connector.py")
assert spec and spec.loader
connector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = connector
spec.loader.exec_module(connector)


def source() -> str:
    return (APP / "connector.py").read_text(encoding="utf-8")


def test_diag_runs_after_both_required_states_exist():
    src = source()
    mirrors = src.index('    mirrors_state = compact_mapping({')
    seat = src.index('    seat_state = compact_mapping({', mirrors)
    climate = src.index('    climate_state = compact_mapping({', seat)
    raw = src.index(
        '    raw_climate_comfort_signals = safe_climate_comfort_raw_signals(attribute(status, "raw"))',
        climate,
    )
    diag = src.index(
        '    log_climate_comfort_diag(climate_state, seat_state, mirrors_state, raw_climate_comfort_signals)',
        raw,
    )
    charge = src.index('    charge_plan = attribute(battery, "charge_plan")', diag)
    assert mirrors < seat < climate < raw < diag < charge


def test_broken_preassignment_call_is_gone():
    src = source()
    mirrors = src.index('    mirrors_state = compact_mapping({')
    seat = src.index('    seat_state = compact_mapping({', mirrors)
    assert 'log_climate_comfort_diag(climate_state, seat_state' not in src[mirrors:seat]


def test_raw_probe_remains_at_early_proven_point():
    src = source()
    window = src.index("log_window_telemetry_diag(window_positions, window_state, raw_window_signals, vehicle_key=remote_id or vin)")
    probe = src.index("log_climate_comfort_raw_probe(raw_climate_probe)", window)
    roof = src.index("roof_opening =", probe)
    assert window < probe < roof


def test_retry_and_physical_routes_unchanged():
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert connector.COMMAND_METHODS["windshield_defrost"] == "windshield_defrost"
    assert connector.COMMAND_METHODS["steering_wheel_heat_on"] == "steering_wheel_heat_on"
    assert connector.COMMAND_METHODS["rearview_mirror_heat_on"] == "rearview_mirror_heat_on"


def test_window_guardrails_preserved():
    src = source()
    assert "WINDOW_TELEMETRY_DIAG vehicle=%s positions=%s states=%s raw_candidates=%s" in src
    assert "vehicle_key=remote_id or vin" in src
    assert 'native = 10 if command == "windows_open" else 0' in src
