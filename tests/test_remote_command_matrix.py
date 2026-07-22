from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_PATH = ROOT / "leaphub_gateway" / "connector.py"
spec = importlib.util.spec_from_file_location("leaphub_gateway_contract_connector", CONNECTOR_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("Não foi possível carregar connector.py")
connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector)

expected_methods = {
    "lock": "lock_vehicle",
    "unlock": "unlock_vehicle",
    "find_car": "find_vehicle",
    "trunk_open": "open_trunk",
    "trunk_close": "close_trunk",
    "windows_open": "open_windows",
    "windows_close": "close_windows",
    "sunshade_open": "open_sunshade",
    "sunshade_close": "close_sunshade",
    "climate_on": "ac_on",
    "climate_off": "ac_off",
    "quick_cool": "quick_cool",
    "quick_heat": "quick_heat",
    "windshield_defrost": "windshield_defrost",
    "battery_preheat_on": "battery_preheat",
    "battery_preheat_off": "battery_preheat_off",
    "start_charging": "start_charging",
    "stop_charging": "stop_charging",
    "unlock_charger": "unlock_charger",
    "set_charge_limit": "set_charge_limit",
    "send_destination": "send_destination",
    "steering_wheel_heat_on": "steering_wheel_heat_on",
    "steering_wheel_heat_off": "steering_wheel_heat_off",
    "rearview_mirror_heat_on": "rearview_mirror_heat_on",
    "rearview_mirror_heat_off": "rearview_mirror_heat_off",
}

failures: list[str] = []

def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)

check(connector.CONNECTOR_VERSION == "1.12.13.1", "Versão do Connector divergente")
check(connector.COMMAND_METHODS == expected_methods, "Matriz COMMAND_METHODS divergente")
check(len(connector.COMMAND_METHODS) == 25, "A matriz precisa conter 25 comandos")
check(connector.CLIMATE_VERIFY_COMMANDS == {"climate_on", "climate_off", "quick_cool", "quick_heat"}, "Conjunto de confirmação climática divergente")
check(connector.SAFE_STATE_RETRY_COMMANDS == {"climate_on", "climate_off"}, "Retry seguro climático divergente")

pairs = [
    ("lock", "unlock"),
    ("trunk_open", "trunk_close"),
    ("windows_open", "windows_close"),
    ("sunshade_open", "sunshade_close"),
    ("battery_preheat_on", "battery_preheat_off"),
    ("start_charging", "stop_charging"),
    ("climate_on", "climate_off"),
    ("steering_wheel_heat_on", "steering_wheel_heat_off"),
    ("rearview_mirror_heat_on", "rearview_mirror_heat_off"),
]
for left, right in pairs:
    check(left in connector.COMMAND_METHODS and right in connector.COMMAND_METHODS, f"Par ausente: {left}/{right}")
    check(connector.COMMAND_METHODS[left] != connector.COMMAND_METHODS[right], f"Par usa o mesmo método: {left}/{right}")

check(connector.login_cooldown_seconds("password error limit has reached maximum") == 135, "Cooldown padrão de login deve ser 135s")
check(connector.login_cooldown_seconds("try again in 2 minutes: password error limit") == 135, "Cooldown de dois minutos deve ter margem de 15s")
check(connector.login_cooldown_seconds("try again in 10 hours: password error limit") == 300, "Cooldown de login deve ser limitado a 300s")
check(connector.login_cooldown_seconds("erro comum") == 0, "Erro comum não pode virar cooldown de login")
check(connector.rate_limit_cooldown_seconds("HTTP 429 too many requests") >= 300, "Rate limit deve respeitar mínimo de 300s")
check(connector.rate_limit_cooldown_seconds("password error limit has reached maximum") == 0, "Cooldown de login não pode ser duplicado como rate limit")

redacted = connector.clean_message('token=abc password=secret vin=LFZ12345678901234 Authorization=Bearer-X')
check('abc' not in redacted and 'secret' not in redacted, "Token ou senha não foi removido")
check('LFZ12345678901234' not in redacted, "VIN não foi removido")

if failures:
    raise SystemExit("remote command matrix failed:\n- " + "\n- ".join(failures))
print({"ok": True, "commands": len(expected_methods), "pairs": len(pairs), "cooldown_cases": 6})
