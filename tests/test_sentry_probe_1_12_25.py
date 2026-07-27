from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_PATH = ROOT / "leaphub_gateway" / "connector.py"
spec = importlib.util.spec_from_file_location("leaphub_sentry_probe_connector", CONNECTOR_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("Não foi possível carregar connector.py")
connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector)

assert connector.CONNECTOR_VERSION == "1.12.25"
assert connector.COMMAND_METHODS["sentry_on"] == "sentry_mode_on"
assert connector.COMMAND_METHODS["sentry_off"] == "sentry_mode_off"
assert connector.EXPERIMENTAL_COMMANDS == {"sentry_on", "sentry_off"}

class FakeClient:
    def __init__(self, sentry: bool | None) -> None:
        self._sentry = sentry
        self.vehicle = SimpleNamespace(vin="VIN_TEST", car_id="CAR_TEST")

    def get_vehicle_list(self):
        return [self.vehicle]

    def get_vehicle_status(self, vehicle):
        return SimpleNamespace(
            security=SimpleNamespace(sentry_mode=self._sentry),
            captured_at=None,
            timestamp=None,
        )

for command, raw_state, expected_match, expected_name in (
    ("sentry_on", True, True, "sentry_on"),
    ("sentry_on", False, False, "sentry_off"),
    ("sentry_off", False, True, "sentry_off"),
    ("sentry_off", True, False, "sentry_on"),
):
    client = FakeClient(raw_state)
    sample = connector.read_command_state(client, "VIN_TEST", command, {}, [client.vehicle])
    assert sample["evaluable"] is True
    assert sample["matched"] is expected_match
    assert sample["state"] == expected_name

unknown = FakeClient(None)
sample = connector.read_command_state(unknown, "VIN_TEST", "sentry_on", {}, [unknown.vehicle])
assert sample["evaluable"] is False
assert sample["state"] == "sentry_unknown"

# The experimental guard must remain visible in source so the command cannot
# accidentally become a normal public action during future refactors.
source = CONNECTOR_PATH.read_text(encoding="utf-8")
assert 'parameters.get("experimental_confirmed") is not True' in source
assert '"experimental_commands": experimental_commands' in source
assert 'return_on_fresh_mismatch=False' in source

print({"ok": True, "version": "1.12.25", "feature": "sentry_probe", "cases": 5})
