from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
REQUIREMENTS = (ROOT / "leaphub_gateway" / "requirements.txt").read_text(encoding="utf-8")
TARGET = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()

failures: list[str] = []
checks = 0

def check(ok: bool, message: str) -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(message)

check(TARGET == "1.12.85", "RELEASE_TARGET divergente")
check('ENGINE_VERSION = "1.12.85"' in ENGINE, "engine não está em 1.12.85")
check('CONNECTOR_VERSION = "1.12.85"' in CONNECTOR, "connector não está em 1.12.85")
check('VERSION = "1.12.85"' in SERVER, "server não está em 1.12.85")
check("leapmotor-api==0.3.2" in REQUIREMENTS, "dependência Leapmotor deixou de estar fixada em 0.3.2")

check("class _TelemetryOneShotClient:" in ENGINE, "adaptador one-shot ausente")
check('return self._one_shot("_get_vehicle_list")' in ENGINE, "lista one-shot ausente")
check('return self._one_shot("_get_vehicle_status", vehicle)' in ENGINE, "status one-shot ausente")
check('return self._one_shot("_get_message_list", page_no=page_no, page_size=page_size)' in ENGINE, "mensagens one-shot ausente")
check("telemetry_client = _TelemetryOneShotClient(client)" in ENGINE, "cliente cooperativo não é criado")

start = ENGINE.index("    def _collect_with_session_locked(")
end = ENGINE.index("    def _close_session_locked(", start)
collection = ENGINE[start:end]
check(collection.count("vehicles_value = telemetry_client.get_vehicle_list()") == 2, "lista ainda não usa one-shot nos dois caminhos")
check('get_messages = getattr(telemetry_client, "get_message_list", None)' in collection, "mensagens ainda não usam one-shot")
check("client=telemetry_client," in collection, "serialize_vehicle ainda recebe cliente com retry oculto")
check("vehicles_value = client.get_vehicle_list()" not in collection, "leitura pública de lista reapareceu")
check('get_messages = getattr(client, "get_message_list", None)' not in collection, "leitura pública de mensagens reapareceu")

check("TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in ENGINE, "teto curto de telemetria regrediu")
check("TelemetryYieldForManual" in collection, "handoff manual desapareceu")
check("manual_should_yield" in collection, "callback de prioridade manual desapareceu")
check('ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windows_open", "windows_close", "sunshade_open", "sunshade_close"}' in CONNECTOR, "ACK-first regrediu")
check('return method(vehicle_id, params={"operate": "off"})' in CONNECTOR, "OFF C10 regrediu")
check("repeat_exact_state_command" in CONNECTOR, "retry exato do clima desapareceu")
check("command_attempts < 2" in CONNECTOR, "teto de duas tentativas desapareceu")
check("announce_command_result_async(" in SERVER, "anúncio imediato ao site desapareceu")
check("CONFIRMATION_SUPERSESSION_FAMILIES" in ENGINE, "supersessão desapareceu")

if failures:
    raise SystemExit("manual_handoff_1_12_85 failed:\n- " + "\n- ".join(failures))
print({"ok": True, "checks": checks, "version": TARGET})
