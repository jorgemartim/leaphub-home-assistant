#!/usr/bin/env python3
"""Gateway 1.12.80 — contrato do despacho ACK-first sem rede."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONNECTOR = ROOT / "leaphub_gateway" / "connector.py"
spec = importlib.util.spec_from_file_location("leaphub_gateway_ack_first_contract", CONNECTOR)
if spec is None or spec.loader is None:
    raise SystemExit("Não foi possível carregar connector.py")
connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector)

errors: list[str] = []
checks = 0

def check(value: bool, message: str) -> None:
    global checks
    checks += 1
    if not value:
        errors.append(message)

check(connector.CONNECTOR_VERSION == "1.12.80", "connector version != 1.12.80")
check(connector.ACK_FIRST_COMMANDS == {"lock", "unlock", "climate_on", "quick_cool", "quick_heat"}, "ACK_FIRST_COMMANDS inesperado")
check("climate_off" not in connector.ACK_FIRST_COMMANDS, "climate_off não deve mudar de estratégia nesta rodada")

class FakeClient:
    def __init__(self) -> None:
        self.poll_calls = 0
        self.calls: list[tuple[str, str, object]] = []

    def _poll_remote_control_result(self, **_kwargs):
        self.poll_calls += 1
        return {"done": True}

    def lock_vehicle(self, vin: str):
        self.calls.append(("lock", vin, None))
        self._poll_remote_control_result(vin=vin)
        return {"code": 0, "data": {"remoteCtlId": "lock-1"}}

    def unlock_vehicle(self, vin: str):
        self.calls.append(("unlock", vin, None))
        self._poll_remote_control_result(vin=vin)
        return {"code": 0, "data": {"remoteCtlId": "unlock-1"}}

    def ac_on(self, vin: str, *, params=None):
        self.calls.append(("climate_on", vin, params))
        self._poll_remote_control_result(vin=vin)
        return {"code": 0, "data": {"remoteCtlId": "climate-1"}}

    def ac_switch(self, vin: str, *, params=None):
        self.calls.append(("climate_off", vin, params))
        self._poll_remote_control_result(vin=vin)
        return {"code": 0, "data": {"remoteCtlId": "climate-off-1"}}

fake = FakeClient()
original_poll = fake._poll_remote_control_result
result, deferred = connector.execute_vehicle_command_ack_first(fake.lock_vehicle, "lock", "VIN", {}, "generic")
check(deferred is True, "lock não entrou em ACK-first")
check(fake.poll_calls == 0, "lock ainda executou polling interno")
check(result.get("code") == 0, "lock perdeu ACK da escrita")
# O override precisa desaparecer: a próxima chamada direta deve voltar ao método original.
fake._poll_remote_control_result(vin="VIN")
check(fake.poll_calls == 1, "poll original não foi restaurado")

fake2 = FakeClient()
result, deferred = connector.execute_vehicle_command_ack_first(fake2.ac_on, "climate_on", "VIN", {"target_temperature": 23}, "generic")
check(deferred is True, "climate_on não entrou em ACK-first")
check(fake2.poll_calls == 0, "climate_on ainda executou polling interno")
params = fake2.calls[-1][2]
check(isinstance(params, dict) and params.get("operate") == "auto" and params.get("mode") == "nohotcold", "payload AUTO da 1.12.79 foi perdido")

fake3 = FakeClient()
result, deferred = connector.execute_vehicle_command_ack_first(fake3.ac_switch, "climate_off", "VIN", {}, "generic")
check(deferred is False, "climate_off foi alterado indevidamente")
check(fake3.poll_calls == 1, "climate_off deixou de usar o fluxo homologado")
check(fake3.calls[-1][2] == {"operate": "off"}, "climate_off perdeu operate=off")

source = CONNECTOR.read_text(encoding="utf-8")
check('remote_result_status = "ack_only"' in source, "resultado ACK-first não é distinguido de completed")
check('confirmation_reason = "result_poll_deferred"' in source, "confirmação assíncrona não está sinalizada")
check('"result_poll_deferred": result_poll_deferred' in source, "diagnóstico result_poll_deferred ausente")

if errors:
    raise SystemExit("Gateway 1.12.80 ACK-first contract FAILED:\n - " + "\n - ".join(errors))
print(f"Gateway 1.12.80 ACK-first contract OK ({checks} checks)")
