from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
TARGET = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()

failures: list[str] = []
checks = 0

def check(ok: bool, message: str) -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(message)

check(TARGET == "1.12.82", "RELEASE_TARGET divergente")
check('CONNECTOR_VERSION = "1.12.82"' in CONNECTOR, "connector não está em 1.12.82")
check('ENGINE_VERSION = "1.12.82"' in ENGINE, "engine não está em 1.12.82")
check('VERSION = "1.12.82"' in SERVER, "server não está em 1.12.82")
check('TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0' in ENGINE, "teto de bloqueio automático ausente")
check('self.telemetry_network_timeout_seconds = min(' in ENGINE, "timeout automático derivado ausente")
check('def _telemetry_request_timeout(self, client: Any):' in ENGINE, "contexto de timeout automático ausente")
check('client.timeout = previous' in ENGINE, "timeout original não é restaurado")
check('if origin == "telemetry"' in ENGINE, "login automático não usa teto curto por origem")
check(ENGINE.count('with self._telemetry_request_timeout(client):') >= 7, "lista/status/mensagens/refresh automáticos não usam teto curto")
check('Operação manual recebeu prioridade durante a leitura de status do veículo.' in ENGINE, "status não converte preempção manual")
check('Operação manual recebeu prioridade durante a leitura da lista de veículos.' in ENGINE, "lista não converte preempção manual")
check('Operação manual recebeu prioridade durante a leitura de mensagens.' in ENGINE, "mensagens não convertem preempção manual")

start = ENGINE.index('    def account_auth_status(')
end = ENGINE.index('    def assert_account_cloud_allowed(', start)
auth_read = ENGINE[start:end]
check('with self._db() as db:' in auth_read, "account_auth_status não usa leitura concorrente")
check('with self.lock' not in auth_read, "account_auth_status ainda segura self.lock")

start = ENGINE.index('    def begin_account_auth(')
end = ENGINE.index('    def record_account_auth_success(', start)
auth_write = ENGINE[start:end]
check('with self.lock, self._db() as db:' in auth_write, "mutação de autenticação perdeu self.lock")
check('BEGIN IMMEDIATE' in auth_write, "reserva de login perdeu BEGIN IMMEDIATE")

check('ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat"}' in CONNECTOR, "ACK-first regrediu")
check('return method(vehicle_id, params={"operate": "off"})' in CONNECTOR, "OFF C10 regrediu")
check('repeat_exact_state_command' in CONNECTOR, "retry exato do clima desapareceu")
check('command_attempts < 2' in CONNECTOR, "teto de duas tentativas não está explícito")
check('announce_command_result_async(' in SERVER, "anúncio imediato ao site desapareceu")

if failures:
    raise SystemExit("manual_priority_1_12_82 failed:\n- " + "\n- ".join(failures))
print({"ok": True, "checks": checks, "version": TARGET})
