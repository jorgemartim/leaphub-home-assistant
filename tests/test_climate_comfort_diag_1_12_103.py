from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load("leaphub_connector_climate_112103", APP / "connector.py")


def climate_payload(mode: str):
    return connector.prepare_car_parameters({
        "climate": True,
        "climate_mode": mode,
        "temperature": 24,
        "wind_level": 3,
    })["air_condition"]


def test_prepare_car_auto_is_really_auto():
    payload = climate_payload("auto")
    assert payload["mode"] == "wind"
    assert payload["operate"] == "auto"
    assert payload["temperature"] == "24"
    assert payload["windlevel"] == "3"


def test_prepare_car_cold_hot_and_wind_are_manual():
    for mode in ("cold", "hot", "wind"):
        payload = climate_payload(mode)
        assert payload["mode"] == mode
        assert payload["operate"] == "manual"


def test_prepare_car_generic_alias_stays_auto():
    for mode in ("generic", "nohotcold"):
        payload = climate_payload(mode)
        assert payload["mode"] == "wind"
        assert payload["operate"] == "auto"


def test_prepare_car_steering_and_mirror_do_not_require_air_condition():
    steering = connector.prepare_car_parameters({
        "steering_wheel_heat": True,
        "steering_wheel_level": 2,
    })
    assert "air_condition" not in steering
    assert steering["steeringWheelHeatCtrl"] == {"enable": True, "level": 2}

    mirrors = connector.prepare_car_parameters({"mirror_heat": True})
    assert "air_condition" not in mirrors
    assert mirrors["rearMirrorHeating"] == {"enable": True, "value": 1}


def test_climate_comfort_diag_logs_only_when_snapshot_changes(monkeypatch):
    connector._CLIMATE_COMFORT_DIAG_LAST_SIGNATURE = None
    seen = []
    monkeypatch.setattr(connector, "connector_log", lambda *args: seen.append(args))
    climate = {
        "on": True, "left_temperature_c": 24, "fan_level": 3,
        "mode": "wind", "operate_mode": "manual", "windshield_defrost": False,
    }
    seat = {"steering_wheel_heating": 0, "steering_wheel_minutes": 0}
    mirrors = {"left_heating": False, "right_heating": False, "folded": False}
    assert connector.log_climate_comfort_diag(climate, seat, mirrors) is True
    assert connector.log_climate_comfort_diag(climate, seat, mirrors) is False
    assert len(seen) == 1
    assert seen[0][0] == connector.logging.DEBUG
    seat2 = dict(seat)
    seat2["steering_wheel_heating"] = 1
    assert connector.log_climate_comfort_diag(climate, seat2, mirrors) is True
    assert len(seen) == 2


def test_climate_comfort_diag_excludes_unrelated_fields(monkeypatch):
    connector._CLIMATE_COMFORT_DIAG_LAST_SIGNATURE = None
    seen = []
    monkeypatch.setattr(connector, "connector_log", lambda *args: seen.append(args))
    assert connector.log_climate_comfort_diag(
        {"on": False, "secret_extra": "must-not-log"},
        {"driver_heating": 3, "steering_wheel_heating": 0},
        {"left_heating": False, "folded": True},
    ) is True
    rendered = repr(seen[0])
    assert "secret_extra" not in rendered
    assert "driver_heating" not in rendered
    assert "folded" not in rendered


def test_dedicated_comfort_routes_remain_independent_and_without_retry():
    assert connector.COMMAND_METHODS["windshield_defrost"] == "windshield_defrost"
    assert connector.COMMAND_METHODS["steering_wheel_heat_on"] == "steering_wheel_heat_on"
    assert connector.COMMAND_METHODS["steering_wheel_heat_off"] == "steering_wheel_heat_off"
    assert connector.COMMAND_METHODS["rearview_mirror_heat_on"] == "rearview_mirror_heat_on"
    assert connector.COMMAND_METHODS["rearview_mirror_heat_off"] == "rearview_mirror_heat_off"
    for command in (
        "windshield_defrost",
        "steering_wheel_heat_on", "steering_wheel_heat_off",
        "rearview_mirror_heat_on", "rearview_mirror_heat_off",
    ):
        assert command not in connector.SAFE_STATE_RETRY_COMMANDS


def test_windows_and_sunshade_guardrails_are_unchanged():
    source = (APP / "connector.py").read_text(encoding="utf-8")
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert 'native = 10 if command == "windows_open" else 0' in source
    assert 'def effective_window_open(' in source
    assert 'WINDOW_TELEMETRY_DIAG vehicle=%s positions=%s states=%s raw_candidates=%s' in source
    assert 'vehicle_key=remote_id or vin' in source
    assert 'native = (percent + 5) // 10' in source
