from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
TARGET = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()


def test_release_versions_are_aligned():
    assert (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip() == TARGET
    assert f'version: "{TARGET}"' in (APP / "config.yaml").read_text(encoding="utf-8")
    assert f'ENGINE_VERSION = "{TARGET}"' in (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    assert f'CONNECTOR_VERSION = "{TARGET}"' in (APP / "connector.py").read_text(encoding="utf-8")


def test_seat_commands_use_fast_confirmation_without_retry():
    telemetry = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    connector = (APP / "connector.py").read_text(encoding="utf-8")
    assert 'frozenset({"seat_heat", "seat_ventilation"})' in telemetry
    assert 'COMFORT_FAST_CONFIRMATION_COMMANDS' in telemetry
    assert 'SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}' in connector
    assert 'seat_heat' not in connector.split('SAFE_STATE_RETRY_COMMANDS =', 1)[1].split('}', 1)[0]
    assert 'seat_ventilation' not in connector.split('SAFE_STATE_RETRY_COMMANDS =', 1)[1].split('}', 1)[0]


def test_raw_comfort_diagnostics_are_debug_only():
    connector = (APP / "connector.py").read_text(encoding="utf-8")
    raw = connector[connector.index("def log_climate_comfort_raw_probe"):connector.index("_CLIMATE_COMFORT_DIAG_LAST_SIGNATURE")]
    diag = connector[connector.index("def log_climate_comfort_diag"):connector.index("def window_open")]
    assert "logging.DEBUG" in raw and "logging.INFO" not in raw
    assert "logging.DEBUG" in diag and "logging.INFO" not in diag
