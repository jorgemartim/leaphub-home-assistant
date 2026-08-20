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
        raise RuntimeError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if "leaphub_connector" not in sys.modules:
    load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_cadence_1_12_96", APP / "telemetry_engine.py")


def make_engine(tmp: str):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = tmp
    return telemetry.TelemetryEngine(
        {"telemetry_command_seconds": 12, "telemetry_interactive_seconds": 20},
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )


def close_engine(engine) -> None:
    engine.close_storage()
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()


def test_runtime_early_confirmation_is_command_only() -> None:
    with tempfile.TemporaryDirectory(prefix="leaphub-1-12-96-cadence-") as tmp:
        engine = make_engine(tmp)
        try:
            assert engine.command_cadence == (6, 10, 16, 24, 34, 45, 60, 90)
            assert engine.command_effective_cadence == (5, 5, 8, 24, 34, 45, 60, 90)
            assert engine.interactive_seconds == 6
            assert engine.command_max_polls == 37
            observed = [
                engine._adaptive_interval(["parked"], 0, command_mode=True, command_poll_count=index)[0]
                for index in range(1, 9)
            ]
            # API historica permanece estrutural; o front-load e aplicado apenas no scheduler.
            assert observed == list(engine.command_cadence)
            poll_source = SOURCE[SOURCE.index("    def _poll_subscription("):SOURCE.index("    def _mark_auth_required(", SOURCE.index("    def _poll_subscription("))]
            # 1.12.120 seleciona a escada por família; o valor histórico
            # continua em `engine.command_effective_cadence` e foi validado acima.
            assert "interval = int(active_cadence[cadence_index])" in poll_source
            for state in ("parked", "sleep", "charge_watch"):
                interval, _state, _streak = engine._adaptive_interval([state], 0, interactive=True)
                assert 5 <= interval <= 6
        finally:
            close_engine(engine)


def test_nominal_180s_window_frontloads_without_adding_nominal_reads() -> None:
    base = (6, 10, 16, 24, 34, 45, 60, 90)
    effective = (5, 5, 8, 24, 34, 45, 60, 90)
    def read_times(delays):
        times = [0]
        elapsed = 0
        for delay in delays:
            elapsed += delay
            times.append(elapsed)
        return [value for value in times if value < 180]
    assert read_times(base) == [0, 6, 16, 32, 56, 90, 135]
    assert read_times(effective) == [0, 5, 10, 18, 42, 76, 121]
    assert len(read_times(base)) == len(read_times(effective)) == 7
    assert min(effective) >= 5


def test_structural_guards_remain_present() -> None:
    assert "COMMAND_FIRST_POLL_CEILING_SECONDS = 6" in SOURCE
    assert "INTERACTIVE_SECONDS_CEILING = 6" in SOURCE
    assert "COMMAND_TRANSIENT_BACKOFF = (8, 15, 25, 40, 60, 90)" in SOURCE
    assert "COMMAND_POST_DISPATCH_EARLY_CADENCE = (5, 5, 8)" in SOURCE
    assert "command_effective_cadence_seconds" in SOURCE
