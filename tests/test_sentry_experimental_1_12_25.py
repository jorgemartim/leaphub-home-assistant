from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_PATH = ROOT / "leaphub_gateway" / "connector.py"
spec = importlib.util.spec_from_file_location("leaphub_gateway_sentry_connector", CONNECTOR_PATH)
assert spec is not None and spec.loader is not None
connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector)

assert connector.CONNECTOR_VERSION == "1.12.70"
assert len(connector.COMMAND_METHODS) == 40
assert connector.EXPERIMENTAL_COMMAND_METHODS == {
    "sentry_on": "sentry_mode_on",
    "sentry_off": "sentry_mode_off",
    "prepare_car": "prepare_car",
    "autopark": "autopark",
    "piloted_parking": "piloted_parking",
    "on3_on": "on3_on",
    "on3_off": "on3_off",
    "seat_adjust": "seat_adjust",
    "rear_seats": "rear_seats",
    "fota_download": "fota_download",
    "fota_install": "fota_install",
    "fota_schedule": "fota_schedule",
}
# O Sentinela tem sonda e diagnóstico próprios; nenhum outro experimental os herda.
assert connector.SENTRY_COMMANDS == {"sentry_on", "sentry_off"}
assert set(connector.COMMAND_METHODS).isdisjoint(connector.EXPERIMENTAL_COMMAND_METHODS)
assert len(connector.ALL_COMMAND_METHODS) == 52

source = CONNECTOR_PATH.read_text(encoding="utf-8")
assert 'experimental_confirmed' in source
assert 'command in EXPERIMENTAL_COMMAND_METHODS' in source
assert '"experimental_commands": experimental_commands' in source
assert 'method_name = ALL_COMMAND_METHODS[command]' in source

telemetry = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
assert 'command in {"sentry_on", "sentry_off"}' in telemetry
assert 'security.get("sentry_mode", telemetry.get("sentry_mode"))' in telemetry

class FakeClient:
    def lock_vehicle(self, _vin: str):
        return None

    def sentry_mode_on(self, _vin: str):
        return None

    def sentry_mode_off(self, _vin: str):
        return None

fake_vehicle = {"vin": "TESTVIN0000000001", "model": "C10"}
serialized = connector.serialize_vehicle(fake_vehicle, False, FakeClient())
assert "lock" in serialized["capabilities"]["supported_commands"]
assert "sentry_on" not in serialized["capabilities"]["supported_commands"]
assert serialized["capabilities"]["experimental_commands"] == ["sentry_on", "sentry_off"]

try:
    connector.handle_command({
        "credentials": {"operation_password": "000000"},
        "vehicle_id": "TESTVIN0000000001",
        "command": "sentry_on",
        "parameters": {},
    })
except ValueError as exc:
    assert "confirmação explícita" in str(exc)
else:
    raise AssertionError("Sentinela sem confirmação experimental deveria ser recusado antes de qualquer chamada de rede")
