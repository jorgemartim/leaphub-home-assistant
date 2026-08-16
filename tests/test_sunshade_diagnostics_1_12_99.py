from __future__ import annotations

import importlib.util
import logging
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


connector = load("leaphub_connector", APP / "connector.py")
telemetry = load("leaphub_telemetry_diag_11299", APP / "telemetry_engine.py")


def test_diagnostic_release_does_not_change_physical_sunshade_semantics():
    source = (APP / "connector.py").read_text(encoding="utf-8")
    start = source.index('    if command == "sunshade_position":')
    end = source.index('    if command == "set_speed_limit":', start)
    branch = source[start:end]

    assert "native = (percent + 5) // 10" in branch
    assert branch.count("native = (percent + 5) // 10") == 1
    assert branch.count('return method(vehicle_id, value=str(native))') == 1
    assert "SUNSHADE_DIAG event=dispatch" in branch

    assert "sunshade_position" not in connector.ACK_FIRST_COMMANDS
    assert "sunshade_position" not in connector.SAFE_STATE_RETRY_COMMANDS
    assert connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}


def test_confirmation_matcher_is_identical_but_emits_safe_samples(caplog):
    engine = object.__new__(telemetry.TelemetryEngine)
    caplog.set_level(logging.INFO, logger="leaphub.telemetry")

    context = {"parameters": {"sunshade_position": 50}}
    assert engine._command_confirmation(
        "sunshade_position", {"sunshade_percent": 100}, context
    ) == (False, True)
    assert engine._command_confirmation(
        "sunshade_position", {"sunshade_percent": 50}, context
    ) == (True, True)

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "SUNSHADE_DIAG event=sample" in text
    assert "pedido_site=50%" in text
    assert "valor_nativo=5" in text
    assert "esperado_telemetria=50" in text
    assert "observado=100.000 match=False" in text
    assert "observado=50.000 match=True" in text

    lowered = text.lower()
    for forbidden in ("vin=", "token=", "password=", "cookie=", "authorization="):
        assert forbidden not in lowered


def test_100_percent_still_means_native_10_and_does_not_match_15_percent():
    engine = object.__new__(telemetry.TelemetryEngine)
    context = {"parameters": {"sunshade_position": 100}}
    assert engine._command_confirmation(
        "sunshade_position", {"sunshade_percent": 15}, context
    ) == (False, True)
    assert engine._command_confirmation(
        "sunshade_position", {"sunshade_percent": 100}, context
    ) == (True, True)


def test_existing_11298_contract_remains_the_source_of_confirmation_policy():
    assert "sunshade_position" in telemetry.TELEMETRY_CONFIRMABLE_COMMANDS
    assert telemetry.TelemetryEngine.COMMAND_CONFIRMATION_FIELDS["sunshade_position"] == (
        "sunshade_percent",
    )
    assert telemetry.CONFIRMATION_SUPERSESSION_FAMILIES["sunshade"] == frozenset({
        "sunshade_open", "sunshade_close", "sunshade_position"
    })
