from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_engine_runtime_test", APP / "telemetry_engine.py")
privacy = load_module("leaphub_privacy_runtime_test", APP / "privacy.py")

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


with tempfile.TemporaryDirectory(prefix="leaphub-gateway-test-") as tmp:
    os.environ["LEAPHUB_TELEMETRY_DIR"] = tmp
    options = {
        "telemetry_beta_enabled": True,
        "telemetry_beta_internal_url": "https://example.invalid/telemetry",
        "telemetry_production_enabled": False,
        "telemetry_production_internal_url": "",
        "telemetry_active_seconds": 20,
        "telemetry_charging_seconds": 25,
        "telemetry_parked_seconds": 90,
        "telemetry_sleep_seconds": 600,
    }
    engine = telemetry.TelemetryEngine(
        options,
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )
    credentials = {
        "email": "tester@example.invalid",
        "password": "not-a-real-password",
        "certificate_pem": "certificate",
        "private_key_pem": "private-key",
    }
    payload = {
        "subscription_id": "leaphub-staging-account-77",
        "account_id": 77,
        "credentials": credentials,
        "vehicle_ids": ["vehicle-1"],
        "enabled": True,
    }

    created = engine.upsert("staging", payload)
    with engine.lock, engine._db() as db:
        before = db.execute(
            "SELECT next_run_at,status,config_hash FROM subscriptions WHERE subscription_id=?",
            (payload["subscription_id"],),
        ).fetchone()
    time.sleep(0.02)
    repeated = engine.upsert("staging", payload)
    with engine.lock, engine._db() as db:
        after = db.execute(
            "SELECT next_run_at,status,config_hash FROM subscriptions WHERE subscription_id=?",
            (payload["subscription_id"],),
        ).fetchone()
    check(bool(created.get("ok")), "Primeiro upsert não foi aceito")
    check(bool(repeated.get("deduplicated")), "Upsert idêntico não foi deduplicado")
    check(float(before["next_run_at"]) == float(after["next_run_at"]), "Upsert idêntico alterou a agenda")
    check(str(before["config_hash"]) == str(after["config_hash"]), "Hash da assinatura mudou sem alteração")

    # A mesma conta só pode reservar uma autenticação por vez, e o backoff
    # precisa sobreviver no SQLite com a sequência conservadora definida.
    engine.record_account_auth_success("staging", 77, "test_reset")
    engine.begin_account_auth("staging", 77, "first")
    try:
        engine.begin_account_auth("staging", 77, "parallel")
        failures.append("A segunda autenticação paralela não foi bloqueada")
    except connector.ConnectorLoginCooldownError:
        pass
    with engine.lock, engine._db() as db:
        db.execute(
            "UPDATE account_auth_state SET cooldown_until=0,attempt_guard_until=0 WHERE environment='staging' AND account_id=77"
        )

    delays: list[int] = []
    for index in range(4):
        engine.begin_account_auth("staging", 77, f"blocked_{index}")
        delays.append(engine.record_account_auth_failure("staging", 77, f"blocked_{index}", "login blocked", 135, blocked=True))
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE account_auth_state SET cooldown_until=0,attempt_guard_until=0 WHERE environment='staging' AND account_id=77"
            )
    check(delays == [300, 600, 1200, 1800], f"Backoff progressivo incorreto: {delays}")
    engine.record_account_auth_success("staging", 77, "test_success")
    status = engine.account_auth_status("staging", 77)
    check(not status.get("cooldown") and int(status.get("block_count") or 0) == 0, "Sucesso não limpou o cooldown")

    # Operações manuais reutilizam a sessão já aberta em vez de criar outro login.
    class BorrowedClient:
        pass

    borrowed = BorrowedClient()
    import hashlib
    expected_hash = hashlib.sha256(telemetry.canonical_json(credentials)).hexdigest()
    engine.sessions[payload["subscription_id"]] = {
        "client": borrowed,
        "vehicles": [object()],
        "credential_hash": expected_hash,
        "created_at": time.time(),
        "last_used_at": time.time(),
    }
    original_handle_account = connector.handle_account
    calls: list[tuple[object, object, bool]] = []

    def fake_handle_account(request, sync=False, borrowed_client=None, borrowed_vehicles=None):
        calls.append((borrowed_client, borrowed_vehicles, bool(sync)))
        return {"ok": True, "vehicles": [], "session_reused": borrowed_client is borrowed}

    connector.handle_account = fake_handle_account
    try:
        sync_result = engine.execute_account_operation(
            "staging", {"account_id": 77, "credentials": credentials}, True, "runtime_test"
        )
        test_result = engine.execute_account_operation(
            "staging", {"account_id": 77, **credentials}, False, "runtime_account_test"
        )
    finally:
        connector.handle_account = original_handle_account
    check(
        calls == [(borrowed, None, True), (borrowed, None, False)],
        "Sincronização ou teste não reutilizou a sessão ativa com lista fresca",
    )
    check(bool(sync_result.get("session_reused")) and bool(test_result.get("session_reused")), "Resultado não informou reutilização de sessão")

    def temporary_handle_account(*args, **kwargs):
        raise connector.ConnectorTemporaryError("falha temporária controlada")

    connector.handle_account = temporary_handle_account
    try:
        try:
            engine.execute_account_operation(
                "staging", {"account_id": 77, "credentials": credentials}, True, "runtime_temporary"
            )
            failures.append("Falha temporária não foi propagada")
        except connector.ConnectorTemporaryError as exc:
            check(str(exc) == "falha temporária controlada", "Falha temporária ganhou argumentos incompatíveis")
    finally:
        connector.handle_account = original_handle_account
    engine.record_account_auth_success("staging", 77, "temporary_reset")

    # O estado não pode virar driving só porque READY ou a ignição oscilaram.
    check(engine._state_of({"vehicle_state": "ready", "ready_state": True, "ignition_on": True, "speed_kmh": 0}) == "parked", "READY parado foi interpretado como driving")
    state, candidate, count = engine._confirm_state_transition("parked", "", 0, "sleep")
    check((state, candidate, count) == ("parked", "sleep", 1), "Sleep foi aceito sem confirmação")
    state, candidate, count = engine._confirm_state_transition(state, candidate, count, "sleep")
    state, candidate, count = engine._confirm_state_transition(state, candidate, count, "sleep")
    check(state == "sleep" and candidate == "" and count == 0, "Sleep não foi confirmado após três leituras")

    # Executa o caminho real de persistência da coleta para detectar erros de SQL
    # nas novas colunas de confirmação de estado e sleep progressivo.
    engine.sessions.pop(payload["subscription_id"], None)
    original_collect = engine._collect_with_session
    engine._collect_with_session = lambda *args, **kwargs: {
        "ok": True,
        "vehicles": [{
            "remote_id": "vehicle-1",
            "telemetry": {
                "captured_at": telemetry.utc_iso(),
                "state": "parked",
                "is_parked": True,
                "speed": 0,
            },
        }],
    }
    try:
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET active_until=?,next_run_at=0,status='waiting',last_state=NULL,candidate_state=NULL,candidate_count=0,sleep_streak=0 WHERE subscription_id=?",
                (time.time() + 600, payload["subscription_id"]),
            )
            row = db.execute("SELECT * FROM subscriptions WHERE subscription_id=?", (payload["subscription_id"],)).fetchone()
        engine._poll_subscription(row)
    finally:
        engine._collect_with_session = original_collect
    with engine.lock, engine._db() as db:
        polled = db.execute(
            "SELECT status,last_state,candidate_state,candidate_count,sleep_streak,next_run_at FROM subscriptions WHERE subscription_id=?",
            (payload["subscription_id"],),
        ).fetchone()
    check(str(polled["status"]) == "active" and str(polled["last_state"]) == "parked", "Coleta não persistiu o estado")
    check(float(polled["next_run_at"]) > time.time(), "Coleta não programou a próxima execução")

    # Compatibilidade do destino com assinaturas diferentes da biblioteca.
    captured: list[tuple] = []

    def destination_old(vin, address, latitude, longitude):
        captured.append((vin, address, latitude, longitude))
        return True

    def destination_new(vin, name, address, latitude, longitude):
        captured.append((vin, name, address, latitude, longitude))
        return True

    params = {"name": "Casa", "address": "Rua A", "latitude": -25.0, "longitude": -51.0}
    connector.execute_vehicle_command(destination_old, "send_destination", "VIN-TEST", params)
    connector.execute_vehicle_command(destination_new, "send_destination", "VIN-TEST", params)
    check(len(captured) == 2 and captured[0][1] == "Rua A" and captured[1][1] == "Casa", "Compatibilidade de send_destination falhou")

    protected = privacy.sanitize_log(
        "VIN LHSYNTH1234567890 email tester@example.invalid Charge ID CPSYNTHETIC12345 ip 203.0.113.42 account_id=77 conta=77 Authorization: Bearer synthetic-token"
    )
    for sensitive in ("LHSYNTH1234567890", "tester@example.invalid", "CPSYNTHETIC12345", "203.0.113.42", "account_id=77", "conta=77", "synthetic-token"):
        check(sensitive not in protected, f"Dado sensível permaneceu no log: {sensitive}")

    # O cooldown precisa continuar ativo depois de recriar o motor, simulando
    # uma reinicialização do add-on sem depender de memória do processo.
    engine.record_account_auth_success("staging", 77, "restart_reset")
    engine.begin_account_auth("staging", 77, "restart_test")
    persisted_delay = engine.record_account_auth_failure(
        "staging", 77, "restart_test", "login blocked", 135, blocked=True
    )
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()
        engine._instance_lock_handle = None
    restarted = telemetry.TelemetryEngine(
        options,
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )
    persisted = restarted.account_auth_status("staging", 77)
    check(persisted_delay == 300, "Cooldown persistido não iniciou em cinco minutos")
    check(bool(persisted.get("cooldown")) and int(persisted.get("retry_after_seconds") or 0) > 0, "Cooldown não sobreviveu ao reinício")
    if restarted._instance_lock_handle is not None:
        restarted._instance_lock_handle.close()

if failures:
    raise SystemExit("gateway 1.12.14 runtime failed:\n- " + "\n- ".join(failures))
print({"ok": True, "checks": 22, "version": "1.12.14"})
