from __future__ import annotations

import http.client
import importlib.util
import json
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


failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


with tempfile.TemporaryDirectory(prefix="leaphub-connection-1-12-15-") as tmp:
    base = Path(tmp)
    options_path = base / "options.json"
    options_path.write_text(json.dumps({
        "staging_secret": "s" * 32,
        "production_secret": "p" * 32,
        "telemetry_beta_enabled": False,
        "telemetry_production_enabled": False,
    }))
    os.environ["LEAPHUB_OPTIONS_PATH"] = str(options_path)
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(base / "telemetry")
    os.environ["LEAPHUB_COMMAND_DB_PATH"] = str(base / "security" / "commands.sqlite")
    os.environ["LEAPHUB_NONCE_DB_PATH"] = str(base / "security" / "nonces.sqlite")

    connector = load_module("leaphub_connector", APP / "connector.py")
    telemetry = load_module("leaphub_telemetry_engine", APP / "telemetry_engine.py")
    privacy = load_module("leaphub_privacy", APP / "privacy.py")
    server = load_module("leaphub_connector_server_1_12_15", APP / "connector_server.py")

    server.initialize_command_db()
    server.initialize_nonce_db()

    class AuthStatusStub:
        def __init__(self) -> None:
            self.cooldown = True
            self.remaining = 600

        def account_auth_status(self, _environment, _payload):
            return {
                "managed": True,
                "cooldown": self.cooldown,
                "retry_after_seconds": self.remaining,
            }

    auth_stub = AuthStatusStub()
    real_telemetry = server.TELEMETRY
    server.TELEMETRY = auth_stub
    payload = {
        "request_id": "request-command-000000000001",
        "account_id": 77,
        "vehicle_id": "veh-synthetic",
        "command": "lock",
    }
    try:
        request_hash, replay = server.command_journal_begin("staging", payload)
        check(request_hash is not None and replay is None, "Primeiro comando não entrou no diário")
        server.command_journal_wait_auth(request_hash, payload["request_id"], 1200)

        duplicate_hash, duplicate = server.command_journal_begin("staging", payload)
        check(duplicate_hash is None, "Backoff de 20 minutos criou um segundo comando")
        check(isinstance(duplicate, dict) and duplicate.get("status") == "waiting_auth", "Backoff legítimo foi reparado como falha")
        check(int((duplicate or {}).get("retry_after_seconds") or 0) > 300, "Backoff acima de cinco minutos foi truncado")

        status = server.command_journal_status("staging", {"request_id": payload["request_id"]})
        check(status.get("status") == "waiting_auth", "Consulta do comando invalidou um cooldown legítimo")
        check(not status.get("stale_login_cooldown_repaired"), "Cooldown progressivo foi classificado como versão antiga")

        # Simula o relógio local chegando ao retry_at enquanto o coordenador
        # global ainda informa bloqueio. O POST idempotente deve continuar na fila.
        row = server.cached_command(request_hash) or {}
        waiting = json.loads(str(row.get("response_json") or "{}"))
        waiting["retry_at"] = time.time() - 1
        waiting["retry_after_seconds"] = 1200
        raw = json.dumps(waiting, ensure_ascii=False, separators=(",", ":"))
        server.cache_command(
            request_hash,
            str(row.get("payload_hash") or ""),
            "waiting_auth",
            raw,
            float(row.get("created_at") or time.time()),
            time.time(),
            time.time() + 1800,
        )
        with server.command_db(0.5) as db:
            db.execute(
                "UPDATE command_requests SET status='waiting_auth',response_json=?,updated_at=?,expires_at=? WHERE request_hash=?",
                (raw, time.time(), time.time() + 1800, request_hash),
            )
            db.commit()
        still_hash, still_waiting = server.command_journal_begin("staging", payload)
        check(still_hash is None and bool((still_waiting or {}).get("duplicate")), "Cooldown global ativo liberou novo envio")
        check(int((still_waiting or {}).get("retry_after_seconds") or 0) == 600, "Espera não acompanhou o coordenador global")

        auth_stub.cooldown = False
        resumed_hash, resumed = server.command_journal_begin("staging", payload)
        check(resumed_hash == request_hash and resumed is None, "Comando não retomou após liberação global")
    finally:
        server.TELEMETRY = real_telemetry

    # Um refresh lógico não pode chamar três aliases após uma falha.
    engine = real_telemetry

    class AliasClient:
        def __init__(self) -> None:
            self.calls = 0

        def refresh(self):
            self.calls += 1
            return False

        refresh_session = refresh
        refresh_token = refresh

    alias = AliasClient()
    check(engine._try_refresh_client_session(alias) is False, "Refresh falso foi aceito")
    check(alias.calls == 1, f"Aliases equivalentes fizeram {alias.calls} chamadas")

    class TransientRefreshClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def refresh_session(self):
            self.calls.append("refresh_session")
            raise RuntimeError("gateway timeout")

        def refresh_token(self):
            self.calls.append("refresh_token")
            return True

    transient = TransientRefreshClient()
    try:
        engine._try_refresh_client_session(transient)
        failures.append("Timeout de refresh não foi classificado como temporário")
    except connector.ConnectorTemporaryError:
        pass
    check(transient.calls == ["refresh_session"], f"Refresh temporário multiplicou chamadas: {transient.calls}")

    class CooldownRefreshClient(TransientRefreshClient):
        def refresh_session(self):
            self.calls.append("refresh_session")
            raise RuntimeError("Password error limit has reached maximum, try again in 300 seconds")

    cooldown_client = CooldownRefreshClient()
    try:
        engine._try_refresh_client_session(cooldown_client)
        failures.append("Cooldown de refresh não foi preservado")
    except connector.ConnectorLoginCooldownError as exc:
        check(exc.retry_after_seconds >= 300, "Retry-After do refresh foi reduzido incorretamente")
    check(cooldown_client.calls == ["refresh_session"], "Cooldown chamou um segundo método de refresh")

    # HTTP/1.1 persistente: duas verificações de saúde na mesma conexão.
    httpd = server.ConnectorHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=3)
    try:
        connection.request("GET", "/health")
        first = connection.getresponse()
        first.read()
        first_socket = connection.sock
        check(first.version == 11, "Gateway não respondeu em HTTP/1.1")
        check((first.getheader("Connection") or "").lower() != "close", "Gateway ainda força Connection: close")
        connection.request("GET", "/health")
        second = connection.getresponse()
        second.read()
        check(connection.sock is first_socket, "A segunda chamada não reutilizou a conexão TCP")
        check(second.status == 200, "Segunda chamada keepalive falhou")
    finally:
        connection.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)

    real_telemetry.stop()
    if real_telemetry._instance_lock_handle is not None:
        real_telemetry._instance_lock_handle.close()

if failures:
    raise SystemExit("connection resilience 1.12.15 failed:\n- " + "\n- ".join(failures))
print({"ok": True, "checks": 17, "version": "1.12.15"})
