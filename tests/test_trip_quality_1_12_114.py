from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"nao foi possivel carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_trip_quality_test_engine", APP / "telemetry_engine.py")
TelemetryEngine = telemetry.TelemetryEngine


def close_engine(engine) -> None:
    engine.close_storage()
    handle = getattr(engine, "_instance_lock_handle", None)
    if handle is not None:
        handle.close()


def make_engine(tmp: str) -> TelemetryEngine:
    os.environ["LEAPHUB_TELEMETRY_DIR"] = tmp
    return TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": "https://example.invalid/telemetry",
        },
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )


def test_additive_trip_fields_do_not_replace_legacy_speed_or_odometer() -> None:
    source = (APP / "connector.py").read_text(encoding="utf-8")
    assert '"speed_kmh": speed_value,' in source
    assert '"odometer_km": numeric(attribute(driving, "total_mileage"))' in source
    assert 'raw_vehicle_speed_kmh = map_numeric(cloud_scalars, "1319")' in source
    assert 'raw_odometer_km = map_numeric(cloud_scalars, "1318")' in source
    assert '"raw_vehicle_speed_kmh": raw_vehicle_speed_kmh,' in source
    assert '"raw_odometer_km": raw_odometer_km,' in source
    assert '"vehicle_timestamp": vehicle_timestamp,' in source


def test_missing_signed_frame_reuses_remembered_southern_sign() -> None:
    value, sign, pending, source = TelemetryEngine._trip_resolve_axis(
        25.1234, None, -1, 0
    )
    assert value == -25.1234
    assert sign == -1
    assert pending == 0
    assert source == "remembered_sign_memory"


def test_isolated_false_positive_frame_does_not_flip_hemisphere() -> None:
    value, sign, pending, source = TelemetryEngine._trip_resolve_axis(
        25.1234, 1, -1, 0
    )
    assert value == -25.1234
    assert sign == -1
    assert pending == 1
    assert source == "remembered_sign_guard"


def test_positive_flip_requires_ten_confirmations_away_from_meridian() -> None:
    pending = 0
    remembered = -1
    value = None
    source = ""
    for _ in range(10):
        value, remembered, pending, source = TelemetryEngine._trip_resolve_axis(
            25.1234, 1, remembered, pending
        )
    assert value == 25.1234
    assert remembered == 1
    assert pending == 0
    assert source == "confirmed_hemisphere_crossing"


def test_real_crossing_near_meridian_is_not_blocked() -> None:
    value, sign, pending, source = TelemetryEngine._trip_resolve_axis(
        0.4, 1, -1, 0
    )
    assert value == 0.4
    assert sign == 1
    assert pending == 0
    assert source == "signed_signal"


def test_negative_signed_frame_is_authoritative_immediately() -> None:
    value, sign, pending, source = TelemetryEngine._trip_resolve_axis(
        25.5, -1, 1, 7
    )
    assert value == -25.5
    assert sign == -1
    assert pending == 0
    assert source == "signed_signal"


def test_trip_burst_is_separate_from_legacy_and_command_cadence() -> None:
    with tempfile.TemporaryDirectory(prefix="leaphub-trip-114-") as tmp:
        engine = make_engine(tmp)
        try:
            assert engine.active_seconds == 20
            assert engine.trip_driving_seconds == 8
            assert engine.command_effective_cadence[:3] == (5, 5, 8)
            legacy_interval, state, _ = engine._adaptive_interval(
                ["driving"], 0, interactive=False, command_mode=False
            )
            assert state == "driving"
            assert legacy_interval == engine.active_seconds
            interactive_interval, _, _ = engine._adaptive_interval(
                ["driving"], 0, interactive=True, command_mode=False
            )
            assert interactive_interval <= 6
        finally:
            close_engine(engine)


def test_duplicate_cloud_frames_back_off_and_new_frame_returns_to_8s() -> None:
    with tempfile.TemporaryDirectory(prefix="leaphub-trip-backoff-") as tmp:
        engine = make_engine(tmp)
        try:
            vehicle = {
                "remote_id": "car-1",
                "telemetry": {
                    "vehicle_state": "driving",
                    "is_parked": False,
                    "speed_kmh": 40,
                    "raw_vehicle_speed_kmh": 41,
                    "raw_odometer_km": 1000,
                    "vehicle_timestamp": "2026-08-18T18:00:00-03:00",
                    "latitude": -24.75,
                    "longitude": -51.75,
                },
            }
            intervals = [
                engine._trip_poll_interval_for_vehicles("sub-1", [vehicle])[0]
                for _ in range(5)
            ]
            assert intervals == [8, 8, 10, 12, 20], intervals

            vehicle["telemetry"]["vehicle_timestamp"] = "2026-08-18T18:00:08-03:00"
            interval, duplicate_count = engine._trip_poll_interval_for_vehicles(
                "sub-1", [vehicle]
            )
            assert interval == 8
            assert duplicate_count == 0
        finally:
            close_engine(engine)


def test_gps_sign_state_is_persisted_without_touching_command_contracts() -> None:
    with tempfile.TemporaryDirectory(prefix="leaphub-trip-gps-") as tmp:
        engine = make_engine(tmp)
        try:
            vehicle = {
                "remote_id": "car-1",
                "telemetry": {
                    "latitude": 24.75,
                    "longitude": 51.75,
                    "gps_signed_latitude_sign": -1,
                    "gps_signed_longitude_sign": -1,
                    "vehicle_timestamp": "2026-08-18T18:00:00-03:00",
                },
            }
            engine._normalize_trip_location("sub-1", vehicle)
            data = vehicle["telemetry"]
            assert data["latitude"] == -24.75
            assert data["longitude"] == -51.75
            assert data["gps_quality"]["latitude_corrected"] is True
            assert data["gps_quality"]["longitude_corrected"] is True

            with engine._db() as db:
                row = db.execute(
                    "SELECT latitude_sign,longitude_sign FROM vehicle_location_signs "
                    "WHERE subscription_id='sub-1' AND remote_id='car-1'"
                ).fetchone()
            assert row is not None
            assert int(row["latitude_sign"]) == -1
            assert int(row["longitude_sign"]) == -1
        finally:
            close_engine(engine)


def test_frozen_physical_and_confirmation_contracts_remain_present() -> None:
    connector_source = (APP / "connector.py").read_text(encoding="utf-8")
    engine_source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    config_source = (APP / "config.yaml").read_text(encoding="utf-8")

    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert connector.ACK_FIRST_COMMANDS == {
        "lock",
        "unlock",
        "climate_on",
        "climate_off",
        "quick_cool",
        "quick_heat",
        "trunk_open",
        "trunk_close",
    }
    assert 'if command in {"windows_open", "windows_close"} and window_native_scale == 10:' in connector_source
    assert 'params["wshld"] = "0"' in connector_source
    assert "COMMAND_POST_DISPATCH_EARLY_CADENCE = (5, 5, 8)" in engine_source
    release_target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
    config_version_line = next(
        line.strip()
        for line in config_source.splitlines()
        if line.strip().startswith("version:")
    )
    config_version = config_version_line.split('"', 2)[1]

    def version_tuple(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in value.split("."))

    # Publicacao em duas fases:
    # - branch staged: config pode estar atras do RELEASE_TARGET;
    # - copia efemera do CI: config e promovido ao RELEASE_TARGET.
    # O contrato nao pode carimbar a versao publicada anterior.
    assert version_tuple(config_version) <= version_tuple(release_target)
