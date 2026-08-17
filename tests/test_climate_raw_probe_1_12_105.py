from __future__ import annotations
import importlib.util, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))

spec = importlib.util.spec_from_file_location("leaphub_connector_probe_112105", APP / "connector.py")
assert spec and spec.loader
connector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = connector
spec.loader.exec_module(connector)

def test_probe_logs_empty_once(monkeypatch):
    connector._CLIMATE_COMFORT_RAW_PROBE_LAST_SIGNATURE = None
    seen = []
    monkeypatch.setattr(connector, "connector_log", lambda *args: seen.append(args))
    assert connector.log_climate_comfort_raw_probe({}) is True
    assert connector.log_climate_comfort_raw_probe({}) is False
    assert len(seen) == 1
    assert seen[0][1] == "CLIMATE_RAW_PROBE raw_candidates=%s"

def test_probe_logs_each_raw_change(monkeypatch):
    connector._CLIMATE_COMFORT_RAW_PROBE_LAST_SIGNATURE = None
    seen = []
    monkeypatch.setattr(connector, "connector_log", lambda *args: seen.append(args))
    assert connector.log_climate_comfort_raw_probe({"signal.1938": 0}) is True
    assert connector.log_climate_comfort_raw_probe({"signal.1938": 1}) is True
    assert len(seen) == 2

def test_probe_is_wired_immediately_after_window_diag():
    source = (APP / "connector.py").read_text(encoding="utf-8")
    window = source.index("log_window_telemetry_diag(window_positions, window_state, raw_window_signals)")
    probe_extract = source.index('raw_climate_probe = safe_climate_comfort_raw_signals(attribute(status, "raw"))', window)
    probe_log = source.index("log_climate_comfort_raw_probe(raw_climate_probe)", probe_extract)
    roof = source.index("roof_opening =", probe_log)
    assert window < probe_extract < probe_log < roof

def test_existing_typed_diag_still_exists():
    source = (APP / "connector.py").read_text(encoding="utf-8")
    assert "CLIMATE_COMFORT_DIAG climate=%s comfort=%s mirrors=%s raw_candidates=%s" in source

def test_physical_command_and_retry_guardrails():
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert connector.COMMAND_METHODS["windshield_defrost"] == "windshield_defrost"
    assert connector.COMMAND_METHODS["steering_wheel_heat_on"] == "steering_wheel_heat_on"
    assert connector.COMMAND_METHODS["rearview_mirror_heat_on"] == "rearview_mirror_heat_on"

def test_window_guardrails():
    source = (APP / "connector.py").read_text(encoding="utf-8")
    assert "WINDOW_TELEMETRY_DIAG positions=%s states=%s raw_candidates=%s" in source
    assert 'native = 10 if command == "windows_open" else 0' in source
