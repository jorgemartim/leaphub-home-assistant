from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_resilience", APP / "telemetry_engine.py")

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


with tempfile.TemporaryDirectory(prefix="leaphub-resilience-") as tmp:
    os.environ["LEAPHUB_TELEMETRY_DIR"] = tmp
    options = {
        "telemetry_beta_enabled": True,
        "telemetry_beta_internal_url": "https://example.invalid/telemetry",
        "telemetry_background_enabled": False,
        "telemetry_session_idle_seconds": 1800,
        "telemetry_vehicle_list_cache_seconds": 1800,
        "telemetry_message_cache_seconds": 1800,
        "telemetry_request_timeout_seconds": 15,
    }
    engine = telemetry.TelemetryEngine(
        options,
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )
    credentials = {
        "email": "cache@example.invalid",
        "password": "synthetic-password",
        "certificate_pem": "certificate",
        "private_key_pem": "private-key",
    }
    payload = {
        "subscription_id": "leaphub-staging-account-501",
        "account_id": 501,
        "credentials": credentials,
        "vehicle_ids": ["veh-501"],
        "enabled": True,
    }
    engine.upsert("staging", payload)

    class CloseTracker:
        def __init__(self) -> None:
            self.closed = 0

        def close(self) -> None:
            self.closed += 1

    close_tracker = CloseTracker()
    engine.sessions[payload["subscription_id"]] = {
        "client": close_tracker,
        "temp_dir": Path(tmp) / "session-keep",
        "credential_hash": hashlib.sha256(telemetry.canonical_json(credentials)).hexdigest(),
        "created_at": time.time(),
        "last_used_at": time.time(),
        "vehicles": [],
        "vehicles_cached_at": 0.0,
        "messages": [],
        "messages_cached_at": 0.0,
    }
    with engine.lock, engine._db() as db:
        db.execute(
            "UPDATE subscriptions SET active_until=?,status='active',next_run_at=0 WHERE subscription_id=?",
            (time.time() - 1, payload["subscription_id"]),
        )
        row = db.execute("SELECT * FROM subscriptions WHERE subscription_id=?", (payload["subscription_id"],)).fetchone()
    engine._poll_subscription(row)
    check(payload["subscription_id"] in engine.sessions, "Fim da janela ativa encerrou uma sessão saudável")
    check(close_tracker.closed == 0, "Cliente saudável foi fechado ao entrar em idle")

    engine._maintenance()
    check(payload["subscription_id"] in engine.sessions, "Maintenance fechou sessão recente")
    engine.sessions[payload["subscription_id"]]["last_used_at"] = time.time() - 1900
    engine._maintenance()
    check(payload["subscription_id"] not in engine.sessions, "Sessão realmente inativa não foi descartada")
    check(close_tracker.closed == 1, "Sessão inativa não fechou o cliente uma única vez")

    class MessagePage:
        messages = [object()]

    class Vehicle:
        car_id = "veh-501"
        vin = "VIN-SYNTHETIC-501"

    class CachedClient:
        def __init__(self) -> None:
            self.vehicle_calls = 0
            self.message_calls = 0
            self.closed = 0

        def get_vehicle_list(self):
            self.vehicle_calls += 1
            return [Vehicle()]

        def get_message_list(self, page_no=1, page_size=100):
            self.message_calls += 1
            return MessagePage()

        def close(self) -> None:
            self.closed += 1

    client = CachedClient()
    sid = payload["subscription_id"]
    engine.sessions[sid] = {
        "client": client,
        "temp_dir": Path(tmp) / "session-cache",
        "credential_hash": hashlib.sha256(telemetry.canonical_json(credentials)).hexdigest(),
        "created_at": time.time(),
        "last_used_at": time.time(),
        "vehicles": [],
        "vehicles_cached_at": 0.0,
        "messages": [],
        "messages_cached_at": 0.0,
    }
    original_serialize = connector.serialize_vehicle
    serialize_calls = 0

    def fake_serialize(item, **kwargs):
        nonlocal_holder[0] += 1
        return {"remote_id": "veh-501", "telemetry": {"state": "parked"}}

    nonlocal_holder = [0]
    connector.serialize_vehicle = fake_serialize
    try:
        first = engine._collect_with_session_locked(sid, "staging", 501, credentials, {"veh-501"})
        second = engine._collect_with_session_locked(sid, "staging", 501, credentials, {"veh-501"})
    finally:
        connector.serialize_vehicle = original_serialize
    check(bool(first.get("ok")) and bool(second.get("ok")), "Coleta com cache falhou")
    check(client.vehicle_calls == 1, f"Lista de veículos foi consultada {client.vehicle_calls} vezes em duas coletas")
    check(client.message_calls == 1, f"Mensagens foram consultadas {client.message_calls} vezes em duas coletas")
    check(nonlocal_holder[0] == 2, "Estado do veículo deixou de ser serializado em cada coleta")

    class ExpiredClient(CachedClient):
        def get_vehicle_list(self):
            raise RuntimeError("invalid token: session expired")

    expired = ExpiredClient()
    engine.sessions[sid] = {
        "client": expired,
        "temp_dir": Path(tmp) / "session-expired",
        "credential_hash": hashlib.sha256(telemetry.canonical_json(credentials)).hexdigest(),
        "created_at": time.time(),
        "last_used_at": time.time(),
        "vehicles": [],
        "vehicles_cached_at": 0.0,
        "messages": [],
        "messages_cached_at": 0.0,
    }
    try:
        engine._collect_with_session_locked(sid, "staging", 501, credentials, {"veh-501"})
        failures.append("Token expirado não gerou erro específico")
    except connector.ConnectorSessionExpiredError:
        pass
    check(sid not in engine.sessions, "Sessão explicitamente expirada permaneceu em memória")
    check(expired.closed == 1, "Cliente expirado não foi fechado exatamente uma vez")

    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()

# OCPP: fila limitada, ordem preservada e comandos pendentes encerrados junto da conexão.
with tempfile.TemporaryDirectory(prefix="leaphub-ocpp-resilience-") as tmp:
    os.environ["LEAPHUB_RUNTIME_DIR"] = tmp
    os.environ["LEAPHUB_OCPP_STATE_DB"] = str(Path(tmp) / "state.sqlite")
    os.environ["LEAPHUB_LOG_FILE"] = str(Path(tmp) / "ocpp.log")
    os.environ["LEAPHUB_STATUS_FILE"] = str(Path(tmp) / "status.json")
    os.environ["LEAPHUB_PID_FILE"] = str(Path(tmp) / "pid")
    os.environ["LEAPHUB_OCPP_QUEUE_MAX"] = "100"
    ocpp = load_module("leaphub_ocpp_resilience", APP / "ocpp_gateway.py")
    target = ocpp.ApiTarget("staging", "https://example.invalid/ocpp", "s" * 32)
    for index in range(105):
        action = "Heartbeat" if index < 80 else "StatusNotification"
        ocpp.queue_event(target, "CP-SYNTHETIC", f"msg-{index}", action, {"n": index}, "offline")
    with ocpp.state_db() as db:
        rows = db.execute("SELECT message_id,ocpp_action FROM event_queue ORDER BY id").fetchall()
    check(len(rows) <= 100, "Fila OCPP ultrapassou o limite configurado")
    check(ocpp.has_pending_event(target, "CP-SYNTHETIC"), "Backlog OCPP não foi detectado")
    for index in range(105):
        ocpp.queue_command_result(target, "CP-SYNTHETIC", index + 1, "completed", {"n": index}, "", "offline")
    with ocpp.state_db() as db:
        result_count = int(db.execute("SELECT COUNT(*) FROM command_result_queue").fetchone()[0])
    check(result_count <= 100, "Fila de resultados OCPP ultrapassou o limite configurado")

    class DummyReader:
        async def readexactly(self, _size: int):
            raise asyncio.IncompleteReadError(partial=b"", expected=_size)

    class DummyWriter:
        def __init__(self) -> None:
            self.closing = False

        def is_closing(self) -> bool:
            return self.closing

        def write(self, _data: bytes) -> None:
            pass

        async def drain(self) -> None:
            pass

        def close(self) -> None:
            self.closing = True

    async def pending_disconnect_test() -> None:
        connection = ocpp.ChargePointConnection(
            "CP-SYNTHETIC", target, {}, DummyReader(), DummyWriter(), "192.0.2.1"
        )
        future = asyncio.get_running_loop().create_future()
        connection.pending_calls["pending"] = future
        await connection.run()
        check(future.done(), "Comando pendente não foi encerrado após desconexão")
        check(isinstance(future.exception(), ConnectionError), "Comando pendente não recebeu erro de conexão")

    asyncio.run(pending_disconnect_test())

if failures:
    raise SystemExit("resilience 1.12.15 failed:\n- " + "\n- ".join(failures))
print({"ok": True, "checks": 16, "version": "1.12.15"})
