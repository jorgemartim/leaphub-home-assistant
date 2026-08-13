from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"não foi possível carregar {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

connector = load("gw183_connector", ROOT / "leaphub_gateway" / "connector.py")
sys.modules["leaphub_connector"] = connector

# O pacote incremental não inclui módulos runtime inalterados. Para este contrato
# unitário, injete stubs mínimos antes de carregar telemetry_engine; o teste usa
# somente registro/supersessão de confirmações.
import types
_orch = types.ModuleType("leaphub_connection_orchestrator")
_orch.ORCHESTRATOR = object()
sys.modules["leaphub_connection_orchestrator"] = _orch
_evt = types.ModuleType("leaphub_event_transport")
_evt.EVENT_TRANSPORT = object()
sys.modules["leaphub_event_transport"] = _evt

telemetry = load("gw183_telemetry", ROOT / "leaphub_gateway" / "telemetry_engine.py")

checks = 0
failures: list[str] = []
def check(cond: bool, msg: str) -> None:
    global checks
    checks += 1
    if not cond:
        failures.append(msg)

check(connector.CONNECTOR_VERSION == "1.12.83", "connector version")
expected_ack = {
    "lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat",
    "trunk_open", "trunk_close", "windows_open", "windows_close", "sunshade_open", "sunshade_close",
}
check(connector.ACK_FIRST_COMMANDS == expected_ack, "ACK-first set")

class FakeClient:
    def __init__(self) -> None:
        self.poll_calls = 0
        self.remote_calls = 0
    def _poll_remote_control_result(self, *_a, **_kw):
        self.poll_calls += 1
        return {"status": "completed"}
    def _state_call(self, _vin: str):
        self.remote_calls += 1
        return self._poll_remote_control_result("remote-id")
    open_trunk = _state_call
    close_trunk = _state_call
    open_windows = _state_call
    close_windows = _state_call
    open_sunshade = _state_call
    close_sunshade = _state_call

for command, method_name in [
    ("trunk_open", "open_trunk"), ("trunk_close", "close_trunk"),
    ("windows_open", "open_windows"), ("windows_close", "close_windows"),
    ("sunshade_open", "open_sunshade"), ("sunshade_close", "close_sunshade"),
]:
    client = FakeClient()
    original = client._poll_remote_control_result
    result, deferred = connector.execute_vehicle_command_ack_first(
        getattr(client, method_name), command, "VINTEST", {}, "generic"
    )
    check(deferred is True, f"{command} deve deferir result poll")
    check(client.poll_calls == 0, f"{command} não pode executar poll síncrono")
    check(client.remote_calls == 1, f"{command} deve transmitir uma vez")
    check(callable(client._poll_remote_control_result), f"{command} deve restaurar poll")
    client._poll_remote_control_result("x")
    check(client.poll_calls == 1, f"{command} poll restaurado deve funcionar")


# Guardrails herdados da 1.12.82: a nova separação não pode desfazer a prioridade
# manual, o OFF C10 nem o anúncio imediato ao Site.
ENGINE_SOURCE = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR_SOURCE = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
SERVER_SOURCE = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
TARGET = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
check(TARGET == "1.12.83", "RELEASE_TARGET")
check('TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0' in ENGINE_SOURCE, "teto automático 4s preservado")
check('self.telemetry_network_timeout_seconds = min(' in ENGINE_SOURCE, "timeout automático derivado preservado")
check('def _telemetry_request_timeout(self, client: Any):' in ENGINE_SOURCE, "context manager de timeout preservado")
check('client.timeout = previous' in ENGINE_SOURCE, "timeout normal precisa ser restaurado")
check(ENGINE_SOURCE.count('with self._telemetry_request_timeout(client):') >= 7, "rede automática continua sob teto curto")
check('with self.lock' not in ENGINE_SOURCE[ENGINE_SOURCE.index('    def account_auth_status('):ENGINE_SOURCE.index('    def assert_account_cloud_allowed(')], "leitura auth não pode recuperar lock global")
check('BEGIN IMMEDIATE' in ENGINE_SOURCE[ENGINE_SOURCE.index('    def begin_account_auth('):ENGINE_SOURCE.index('    def record_account_auth_success(')], "mutação auth continua transacional")
check('return method(vehicle_id, params={"operate": "off"})' in CONNECTOR_SOURCE, "OFF C10 preservado")
check('repeat_exact_state_command' in CONNECTOR_SOURCE, "retry exato preservado")
check('command_attempts < 2' in CONNECTOR_SOURCE, "teto de duas transmissões preservado")
check('announce_command_result_async(' in SERVER_SOURCE, "anúncio imediato preservado")
check('include_secondary_network=False' in ENGINE_SOURCE, "telemetria FAST não pode abrir rede secundária de imagem")

# A telemetria FAST não pode abrir rede de imagem oficial. Sem pacote em cache,
# allow_network=False precisa retornar None sem chamar nenhum endpoint de imagem.
class NoImageNetwork:
    def __init__(self) -> None:
        self.calls = 0
    def get_car_picture(self, *_a, **_kw):
        self.calls += 1
        raise AssertionError("rede de imagem não deveria ser chamada")
    def download_car_picture_package(self, *_a, **_kw):
        self.calls += 1
        raise AssertionError("download de imagem não deveria ser chamado")

with tempfile.TemporaryDirectory() as tmp:
    old = os.environ.get("LEAPHUB_VEHICLE_IMAGE_DIR")
    os.environ["LEAPHUB_VEHICLE_IMAGE_DIR"] = tmp
    try:
        fake = NoImageNetwork()
        outcome = connector._official_picture_package(fake, object(), "vehicle-x", allow_network=False)
        check(outcome is None, "sem cache a imagem FAST deve ser omitida")
        check(fake.calls == 0, "FAST não pode abrir rede de imagem")
    finally:
        if old is None:
            os.environ.pop("LEAPHUB_VEHICLE_IMAGE_DIR", None)
        else:
            os.environ["LEAPHUB_VEHICLE_IMAGE_DIR"] = old

# Confirmação oposta posterior deve superseder a anterior imediatamente.
db = sqlite3.connect(":memory:")
db.row_factory = sqlite3.Row
db.execute("""
CREATE TABLE command_confirmations (
    confirmation_id TEXT PRIMARY KEY,
    subscription_id TEXT,
    request_id TEXT,
    command_key TEXT,
    command_vehicle_id TEXT,
    context_json TEXT,
    started_at REAL,
    expires_at REAL,
    poll_count INTEGER DEFAULT 0,
    evaluated_samples INTEGER DEFAULT 0,
    stale_samples INTEGER DEFAULT 0,
    status TEXT,
    resolution TEXT,
    resolved_at REAL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
)
""")
engine = telemetry.TelemetryEngine.__new__(telemetry.TelemetryEngine)
now = 1000.0
now_iso = "2026-08-13T22:00:00Z"
first, reused = engine._register_confirmation(db, "sub", "lock", "car", "req-lock", "{}", 180, now, now_iso)
check(bool(first) and reused is False, "lock inicial deve criar confirmação")
second, reused2 = engine._register_confirmation(db, "sub", "unlock", "car", "req-unlock", "{}", 180, now + 1, now_iso)
check(bool(second) and reused2 is False, "unlock novo deve criar confirmação")
old_row = db.execute("SELECT status,resolution FROM command_confirmations WHERE confirmation_id=?", (first,)).fetchone()
new_row = db.execute("SELECT status FROM command_confirmations WHERE confirmation_id=?", (second,)).fetchone()
check(old_row is not None and old_row["status"] == "superseded", "lock antigo deve ser superseded")
check(old_row is not None and old_row["resolution"] == "superseded_by:unlock", "resolução superseded")
check(new_row is not None and new_row["status"] == "pending", "unlock novo permanece pending")
check(len(engine._pending_confirmations(db, "sub")) == 1, "só a intenção mais nova deve ficar pendente")

# Famílias independentes não se cancelam.
third, _ = engine._register_confirmation(db, "sub", "trunk_open", "car", "req-trunk", "{}", 180, now + 2, now_iso)
check(len(engine._pending_confirmations(db, "sub")) == 2, "trunk não deve cancelar unlock")
fourth, _ = engine._register_confirmation(db, "sub", "trunk_close", "car", "req-trunk-close", "{}", 180, now + 3, now_iso)
trunk_old = db.execute("SELECT status FROM command_confirmations WHERE confirmation_id=?", (third,)).fetchone()
check(trunk_old is not None and trunk_old["status"] == "superseded", "trunk_open deve ser superseded por trunk_close")
check(len(engine._pending_confirmations(db, "sub")) == 2, "unlock + trunk_close devem ficar pendentes")

if failures:
    raise SystemExit("Gateway 1.12.83 contract failed:\n- " + "\n- ".join(failures))
print({"ok": True, "checks": checks, "version": connector.CONNECTOR_VERSION})
