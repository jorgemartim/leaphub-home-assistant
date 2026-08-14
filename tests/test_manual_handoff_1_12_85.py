from __future__ import annotations

import ast
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "leaphub_gateway" / "telemetry_engine.py"
ENGINE = ENGINE_PATH.read_text(encoding="utf-8")

class TemporaryError(RuntimeError):
    pass

def load_adapter():
    tree = ast.parse(ENGINE, filename=str(ENGINE_PATH))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == "_TelemetryOneShotClient"
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Any": Any,
        "connector": types.SimpleNamespace(ConnectorTemporaryError=TemporaryError),
    }
    exec(compile(module, str(ENGINE_PATH), "exec"), namespace)
    return namespace["_TelemetryOneShotClient"]

def test_private_one_shot_methods_are_used():
    Adapter = load_adapter()

    class FakeClient:
        delegated = "ok"

        def __init__(self):
            self.calls = []

        def _get_vehicle_list(self):
            self.calls.append("private_list")
            return ["vehicle"]

        def _get_vehicle_status(self, vehicle):
            self.calls.append(("private_status", vehicle))
            return {"status": "ok"}

        def _get_message_list(self, *, page_no=1, page_size=10):
            self.calls.append(("private_messages", page_no, page_size))
            return {"messages": []}

        def get_vehicle_list(self):
            raise AssertionError("public get_vehicle_list não pode rodar na telemetria")

        def get_vehicle_status(self, vehicle):
            raise AssertionError("public get_vehicle_status não pode rodar na telemetria")

        def get_message_list(self, *, page_no=1, page_size=10):
            raise AssertionError("public get_message_list não pode rodar na telemetria")

    raw = FakeClient()
    client = Adapter(raw)

    assert client.get_vehicle_list() == ["vehicle"]
    assert client.get_vehicle_status("V") == {"status": "ok"}
    assert client.get_message_list(page_no=2, page_size=25) == {"messages": []}
    assert client.delegated == "ok"
    assert raw.calls == [
        "private_list",
        ("private_status", "V"),
        ("private_messages", 2, 25),
    ]

def test_missing_private_method_fails_closed():
    Adapter = load_adapter()

    class FutureClient:
        def get_vehicle_list(self):
            return ["would-hide-retry"]

    try:
        Adapter(FutureClient()).get_vehicle_list()
    except TemporaryError:
        return
    raise AssertionError("adaptador caiu no método público em vez de falhar fechado")

if __name__ == "__main__":
    test_private_one_shot_methods_are_used()
    test_missing_private_method_fails_closed()
    print({"ok": True, "tests": 2, "contract": "manual_handoff_1_12_85"})
