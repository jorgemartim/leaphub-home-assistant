from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def test_official_runtime_module_is_installed_and_imported_by_runtime_name():
    docker = (APP / "Dockerfile").read_text(encoding="utf-8")
    telemetry = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    probe = (APP / "official_trip_probe.py").read_text(encoding="utf-8")

    target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
    assert "'official_trip_probe.py': 'leaphub_official_trip_probe.py'" in docker
    assert "import leaphub_official_trip_probe" in docker
    assert f'assert leaphub_official_trip_probe.PROBE_VERSION == "{target}"' in docker
    assert "from leaphub_official_trip_probe import normalize_window, probe_windowed_mileage_energy" in telemetry
    assert "except ModuleNotFoundError:" in telemetry
    assert "from official_trip_probe import normalize_window, probe_windowed_mileage_energy" in telemetry
    assert f'PROBE_VERSION = "{target}"' in probe


def test_hotfix_does_not_change_command_confirmation_contract():
    telemetry = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    connector = (APP / "connector.py").read_text(encoding="utf-8")
    assert "COMMAND_POST_DISPATCH_EARLY_CADENCE = (5, 5, 8)" in telemetry
    assert "COMMAND_FIRST_POLL_CEILING_SECONDS = 6" in telemetry
    assert 'SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}' in connector
    assert '"trunk_open"' in connector and '"trunk_close"' in connector
