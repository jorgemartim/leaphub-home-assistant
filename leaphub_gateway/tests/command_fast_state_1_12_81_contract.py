#!/usr/bin/env python3
"""Gateway 1.12.81 — contrato de resposta rápida preservando o OFF C10."""
from __future__ import annotations
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONNECTOR = ROOT / "leaphub_gateway" / "connector.py"
spec = importlib.util.spec_from_file_location("leaphub_gateway_1_12_81_contract", CONNECTOR)
assert spec and spec.loader
connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector)

errors=[]
checks=0
def check(value: bool, message: str) -> None:
    global checks
    checks += 1
    if not value: errors.append(message)

check(connector.CONNECTOR_VERSION == "1.12.81", "connector version")
check(connector.ACK_FIRST_COMMANDS == {"lock","unlock","climate_on","climate_off","quick_cool","quick_heat"}, "ACK_FIRST_COMMANDS")
check(connector.ALL_COMMAND_METHODS["climate_off"] == "ac_switch", "climate_off method")

class FakeClient:
    def __init__(self):
        self.poll_calls=0
        self.calls=[]
    def _poll_remote_control_result(self,*args,**kwargs):
        self.poll_calls += 1
        return {"status":"completed"}
    def ac_switch(self, vin, params=None):
        self.calls.append((vin, params))
        self._poll_remote_control_result("fake")
        return {"code":0}

client=FakeClient()
result,deferred=connector.execute_vehicle_command_ack_first(client.ac_switch,"climate_off","VIN",{},"generic")
check(deferred is True,"climate_off não diferiu poll")
check(client.poll_calls == 0,"poll interno ainda foi chamado")
check(client.calls == [("VIN", {"operate":"off"})],"payload OFF mudou")
check(callable(client._poll_remote_control_result),"poll não restaurado")

source=CONNECTOR.read_text(encoding="utf-8")
check('verify_climate_state_once_after_settle' in source,"single probe ausente")
check('single_probe' in source,"diagnóstico single probe ausente")
check('telemetry_pending_after_safe_retry' in source,"retry não termina em telemetria")
check('execute_vehicle_command_ack_first,\n                        method,' in source,"segunda transmissão não usa ACK-first")
check('repeat_exact_state_command' in source,"retry exato perdido")
check('time.sleep(delay)' in source,"janela curta de aplicação ausente")
check('Segundo OFF enviado; confirmação física segue pela telemetria sem novo polling síncrono.' in source,"final não documenta telemetria")

server=(ROOT/'leaphub_gateway'/'connector_server.py').read_text(encoding='utf-8')
check('Resultado do comando %s anunciado imediatamente ao site.' in server,"diagnóstico announce success ausente")
check('reconciliação segue pelo ciclo normal' in server,"fallback announce ausente")

if errors:
    raise SystemExit('Gateway 1.12.81 contrato FALHOU:\n - '+'\n - '.join(errors))
print({"ok":True,"checks":checks,"version":connector.CONNECTOR_VERSION})
