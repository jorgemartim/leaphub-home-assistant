from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
SOURCE = (APP / "telemetry_engine.py").read_text(encoding="utf-8")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"nao foi possivel carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_comfort_cadence_1_12_120", APP / "telemetry_engine.py")


def make_engine(tmp: str):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = tmp
    return telemetry.TelemetryEngine(
        {"telemetry_command_seconds": 12, "telemetry_interactive_seconds": 20},
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )


def close_engine(engine) -> None:
    engine.close_storage()
    handle = getattr(engine, "_instance_lock_handle", None)
    if handle is not None:
        handle.close()


def read_times(delays: tuple[int, ...], ceiling: int = 180) -> list[int]:
    times = [0]
    elapsed = 0
    for delay in delays:
        elapsed += delay
        if elapsed >= ceiling:
            break
        times.append(elapsed)
    return times


def test_comfort_uses_bounded_cadence_without_changing_other_commands() -> None:
    with tempfile.TemporaryDirectory(prefix="leaphub-comfort-cadence-120-") as tmp:
        engine = make_engine(tmp)
        try:
            legacy = (5, 5, 8, 24, 34, 45, 60, 90)
            comfort = (5, 5, 8, 10, 10, 12, 24, 34, 45, 60, 90)
            assert engine.command_effective_cadence == legacy
            assert engine.command_comfort_effective_cadence == comfort
            assert engine._command_confirmation_poll_schedule(("quick_heat",)) == comfort
            assert engine._command_confirmation_poll_schedule(("windshield_defrost",)) == comfort
            assert engine._command_confirmation_poll_schedule(("steering_wheel_heat_on",)) == comfort
            assert engine._command_confirmation_poll_schedule(("rearview_mirror_heat_off",)) == comfort
            assert engine._command_confirmation_poll_schedule(("unlock",)) == legacy
            assert engine._command_confirmation_poll_schedule(("windows_close",)) == legacy
            assert engine._command_confirmation_poll_schedule(("sunshade_close",)) == legacy
        finally:
            close_engine(engine)


def test_field_gap_from_18_to_42_seconds_is_removed_only_for_comfort() -> None:
    legacy = (5, 5, 8, 24, 34, 45, 60, 90)
    comfort = (5, 5, 8, 10, 10, 12, 24, 34, 45, 60, 90)
    assert read_times(legacy)[:5] == [0, 5, 10, 18, 42]
    assert read_times(comfort)[:7] == [0, 5, 10, 18, 28, 38, 50]
    assert max(
        right - left
        for left, right in zip(read_times(comfort), read_times(comfort)[1:])
        if right <= 50
    ) <= 12
    assert read_times(legacy) == [0, 5, 10, 18, 42, 76, 121]


def test_scheduler_selection_is_read_only_and_keeps_safety_contracts() -> None:
    poll_start = SOURCE.index("    def _poll_subscription(")
    poll_end = SOURCE.index("    def _mark_auth_required(", poll_start)
    poll_source = SOURCE[poll_start:poll_end]
    assert 'active_command_keys = (item["command_key"] for item in remaining_outcomes)' in poll_source
    assert "active_cadence = self._command_confirmation_poll_schedule(active_command_keys)" in poll_source
    assert "interval = int(active_cadence[cadence_index])" in poll_source
    assert "COMMAND_POST_DISPATCH_EARLY_CADENCE = (5, 5, 8)" in SOURCE
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}
    assert connector.VERIFIED_COMFORT_COMMAND_CONTENT["steering_wheel_heat_on"] == '{"level":"2"}'
    assert connector.VERIFIED_COMFORT_COMMAND_CONTENT["rearview_mirror_heat_on"] == '{"value":"2"}'


def test_release_versions_are_staged_without_advertising_unbuilt_image() -> None:
    assert connector.CONNECTOR_VERSION == "1.12.120"
    assert telemetry.ENGINE_VERSION == "1.12.120"
    assert (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip() == "1.12.120"
    config = (APP / "config.yaml").read_text(encoding="utf-8")
    # A branch candidata anuncia 1.12.119; o validador oficial também executa
    # a suíte sobre uma cópia já promovida para 1.12.120 antes da publicação.
    assert ('version: "1.12.119"' in config) != ('version: "1.12.120"' in config)
