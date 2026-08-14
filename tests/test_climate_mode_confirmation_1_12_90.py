from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load("leaphub_connector_190", APP / "connector.py")
sys.modules.setdefault("leaphub_connector", connector)

_previous_orchestrator = sys.modules.get("leaphub_connection_orchestrator")
_previous_event = sys.modules.get("leaphub_event_transport")
try:
    orch = types.ModuleType("leaphub_connection_orchestrator")
    orch.ORCHESTRATOR = object()
    sys.modules["leaphub_connection_orchestrator"] = orch

    event = types.ModuleType("leaphub_event_transport")
    event.EVENT_TRANSPORT = object()
    sys.modules["leaphub_event_transport"] = event

    telemetry = load("gw190_telemetry", APP / "telemetry_engine.py")
finally:
    if _previous_orchestrator is None:
        sys.modules.pop("leaphub_connection_orchestrator", None)
    else:
        sys.modules["leaphub_connection_orchestrator"] = _previous_orchestrator
    if _previous_event is None:
        sys.modules.pop("leaphub_event_transport", None)
    else:
        sys.modules["leaphub_event_transport"] = _previous_event


def engine():
    return telemetry.TelemetryEngine.__new__(telemetry.TelemetryEngine)


def confirm(command: str, sample: dict):
    return engine()._command_confirmation(command, sample, {})


def test_quick_heat_does_not_confirm_merely_because_hvac_is_on():
    assert confirm("quick_heat", {"climate_on": True}) == (False, False)


def test_quick_heat_rejects_explicit_cooling_mode():
    assert confirm(
        "quick_heat",
        {"climate_on": True, "climate_details": {"mode": 1}},
    ) == (False, True)


def test_quick_heat_confirms_explicit_heating_mode():
    assert confirm(
        "quick_heat",
        {"climate_on": True, "climate_details": {"mode": 3}},
    ) == (True, True)


def test_quick_cool_confirms_explicit_cooling_mode():
    assert confirm(
        "quick_cool",
        {"climate_on": True, "climate_details": {"mode": 1}},
    ) == (True, True)


def test_auto_confirms_mode_zero_only():
    assert confirm(
        "climate_on",
        {"climate_on": True, "climate_details": {"mode": 0}},
    ) == (True, True)
    assert confirm(
        "climate_on",
        {"climate_on": True, "climate_details": {"mode": 3}},
    ) == (False, True)


def test_off_stays_generic_and_does_not_require_mode():
    assert confirm("climate_off", {"climate_on": False}) == (True, True)
    assert confirm("climate_off", {"climate_on": True}) == (False, True)


def test_textual_modes_support_other_models_without_hardcoded_model_name():
    assert confirm(
        "quick_heat",
        {"climate_on": True, "climate_details": {"cooling_and_heating": "hot"}},
    ) == (True, True)
    assert confirm(
        "quick_cool",
        {"climate_on": True, "climate_details": {"operate_mode": "cooling"}},
    ) == (True, True)
    assert confirm(
        "climate_on",
        {"climate_on": True, "climate_details": {"mode": "nohotcold"}},
    ) == (True, True)


def test_unknown_future_mode_fails_closed_not_false_positive():
    assert confirm(
        "quick_heat",
        {"climate_on": True, "climate_details": {"mode": 7}},
    ) == (False, False)


def test_mode_supersession_family_is_preserved():
    family = telemetry.CONFIRMATION_SUPERSESSION_FAMILIES["climate"]
    assert {"climate_on", "climate_off", "quick_cool", "quick_heat"} <= set(family)
