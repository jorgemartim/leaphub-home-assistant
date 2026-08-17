from __future__ import annotations
import importlib.util, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/"leaphub_gateway"
sys.path.insert(0,str(APP))
spec=importlib.util.spec_from_file_location("leaphub_connector_raw_112104",APP/"connector.py")
assert spec and spec.loader
connector=importlib.util.module_from_spec(spec); sys.modules[spec.name]=connector; spec.loader.exec_module(connector)

def test_allowlist_exact():
    assert connector.CLIMATE_COMFORT_SIGNAL_IDS == {
        "49","50","1349","1624","1816","1938","1939","1940","1941","1943",
        "1945","1946","1949","2100","2101","2118","2119","2183","2184","2669","2681","3713"
    }

def test_extractor_blocks_gps_and_unknown():
    raw={"data":{"signal":{"1938":1,"1941":4,"1945":2,"1816":1,"49":1,"50":1,
                           "3725":-25.1,"3724":-51.1,"999999":"x"},"vin":"NO"}}
    assert connector.safe_climate_comfort_raw_signals(raw)=={
        "signal.1816":1,"signal.1938":1,"signal.1941":4,"signal.1945":2,"signal.49":1,"signal.50":1
    }

def test_empty_diag_logs_once(monkeypatch):
    connector._CLIMATE_COMFORT_DIAG_LAST_SIGNATURE=None
    seen=[]
    monkeypatch.setattr(connector,"connector_log",lambda *a: seen.append(a))
    assert connector.log_climate_comfort_diag({}, {}, {}, {}) is True
    assert connector.log_climate_comfort_diag({}, {}, {}, {}) is False
    assert len(seen)==1

def test_raw_change_logs(monkeypatch):
    connector._CLIMATE_COMFORT_DIAG_LAST_SIGNATURE=None
    seen=[]
    monkeypatch.setattr(connector,"connector_log",lambda *a: seen.append(a))
    assert connector.log_climate_comfort_diag({}, {}, {}, {"signal.1816":0}) is True
    assert connector.log_climate_comfort_diag({}, {}, {}, {"signal.1816":1}) is True
    assert len(seen)==2

def test_no_command_or_retry_change():
    assert connector.SAFE_STATE_RETRY_COMMANDS=={"climate_on","climate_off"}
    assert connector.COMMAND_METHODS["windshield_defrost"]=="windshield_defrost"
    assert connector.COMMAND_METHODS["steering_wheel_heat_on"]=="steering_wheel_heat_on"
    assert connector.COMMAND_METHODS["rearview_mirror_heat_on"]=="rearview_mirror_heat_on"
