#!/usr/bin/env python3
from __future__ import annotations

import errno
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
try:
    from leaphub_telemetry_engine import TelemetryEngine
except ModuleNotFoundError:
    try:
        from telemetry_engine import TelemetryEngine
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Módulo interno de telemetria ausente na imagem. Atualize o Leap Hub Gateway."
        ) from exc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    import leaphub_connector as connector
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "Módulo interno leaphub_connector ausente na imagem. Atualize o Leap Hub Gateway."
    ) from exc

VERSION = "1.11.85"
SERVICE = "Leap Hub Leapmotor Connector"
MAX_BODY = 1024 * 1024
WINDOW_SECONDS = 180
STARTED_AT = time.time()
NONCES: dict[str, float] = {}
NONCE_LOCK = threading.Lock()
NONCE_DB_LOCK = threading.Lock()
NONCE_DB_LAST_CLEANUP = 0.0
NONCE_DB_LAST_WARNING = 0.0
NONCE_DB_PATH = Path(os.getenv("LEAPHUB_NONCE_DB_PATH", "/data/security/connector-nonces.sqlite"))
COMMAND_DB_PATH = Path(os.getenv("LEAPHUB_COMMAND_DB_PATH", "/data/security/connector-commands.sqlite"))
COMMAND_CACHE: dict[str, dict[str, Any]] = {}
COMMAND_CACHE_LOCK = threading.RLock()
COMMAND_CACHE_MAX = 2000
ACCOUNT_LOCKS: dict[str, threading.Lock] = {}
ACCOUNT_LOCK_LAST_USED: dict[str, float] = {}
ACCOUNT_LOCKS_GUARD = threading.Lock()
MANUAL_PENDING: dict[str, int] = {}
MANUAL_DEFER_UNTIL: dict[str, float] = {}
MANUAL_PENDING_GUARD = threading.Lock()
COMMAND_WORKERS: dict[str, threading.Thread] = {}
COMMAND_WORKERS_GUARD = threading.Lock()
OPTIONS_PATH = Path(os.getenv("LEAPHUB_OPTIONS_PATH", "/data/options.json"))


def load_options() -> dict[str, Any]:
    try:
        value = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


OPTIONS = load_options()
SECRETS = {
    "staging": str(OPTIONS.get("staging_secret") or "").strip(),
    "production": str(OPTIONS.get("production_secret") or "").strip(),
}
MAX_PARALLEL = max(1, min(8, int(OPTIONS.get("connector_max_parallel") or OPTIONS.get("max_parallel_requests") or 2)))
SEMAPHORE = threading.BoundedSemaphore(MAX_PARALLEL)
MANUAL_WAIT_SECONDS = max(2, min(60, int(OPTIONS.get("connector_manual_wait_seconds") or OPTIONS.get("manual_wait_seconds") or 35)))
LOG_LEVEL = str(OPTIONS.get("log_level") or "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("leaphub.connector")
logging.getLogger("leapmotor_api").setLevel(logging.WARNING)
TELEMETRY: TelemetryEngine


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=connector.json_default).encode("utf-8")


def request_identifier(payload: dict[str, Any]) -> str:
    value = str(payload.get("request_id") or "").strip().lower()
    return value if re.fullmatch(r"[a-z0-9][a-z0-9._:-]{15,95}", value) else ""


def command_payload_hash(payload: dict[str, Any]) -> str:
    safe = {
        "account_id": int(payload.get("account_id") or 0),
        "vehicle_id": str(payload.get("vehicle_id") or "")[:190],
        "vehicle_vin": str(payload.get("vehicle_vin") or "")[:40],
        "command": str(payload.get("command") or "")[:80],
        "parameters": payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {},
    }
    raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=connector.json_default)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def initialize_command_db() -> None:
    """Prepare the journal once; request threads must never renegotiate journal mode."""
    COMMAND_DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sqlite3.connect(COMMAND_DB_PATH, timeout=10.0) as db:
        db.execute("PRAGMA busy_timeout = 10000")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA synchronous = NORMAL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS command_requests ("
            "request_hash TEXT PRIMARY KEY,payload_hash TEXT NOT NULL,status TEXT NOT NULL,"
            "response_json TEXT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,expires_at REAL NOT NULL)"
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_command_requests_expiry ON command_requests(expires_at)")
        db.commit()
    _chmod_private(COMMAND_DB_PATH)


def command_db(timeout: float = 0.75) -> sqlite3.Connection:
    COMMAND_DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    timeout = max(0.05, min(5.0, float(timeout)))
    db = sqlite3.connect(COMMAND_DB_PATH, timeout=timeout)
    db.row_factory = sqlite3.Row
    db.execute(f"PRAGMA busy_timeout = {max(50, int(timeout * 1000))}")
    db.execute("PRAGMA synchronous = NORMAL")
    return db


def prune_command_cache(now: float) -> None:
    expired = [key for key, item in COMMAND_CACHE.items() if float(item.get("expires_at") or 0) < now]
    for key in expired:
        COMMAND_CACHE.pop(key, None)
    if len(COMMAND_CACHE) <= COMMAND_CACHE_MAX:
        return
    oldest = sorted(COMMAND_CACHE.items(), key=lambda item: float(item[1].get("updated_at") or 0))
    for key, _ in oldest[: max(1, len(COMMAND_CACHE) - COMMAND_CACHE_MAX)]:
        COMMAND_CACHE.pop(key, None)


def cache_command(
    request_hash: str,
    payload_hash: str,
    status: str,
    response_json: str | None,
    created_at: float,
    updated_at: float,
    expires_at: float,
) -> None:
    with COMMAND_CACHE_LOCK:
        prune_command_cache(updated_at)
        COMMAND_CACHE[request_hash] = {
            "payload_hash": payload_hash,
            "status": status,
            "response_json": response_json or "",
            "created_at": created_at,
            "updated_at": updated_at,
            "expires_at": expires_at,
        }


def cached_command(request_hash: str) -> dict[str, Any] | None:
    now = time.time()
    with COMMAND_CACHE_LOCK:
        prune_command_cache(now)
        row = COMMAND_CACHE.get(request_hash)
        return dict(row) if isinstance(row, dict) else None


def command_journal_begin(environment: str, payload: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    request_id = request_identifier(payload)
    if not request_id:
        return None, None
    now = time.time()
    request_hash = hashlib.sha256(f"{environment}|{request_id}".encode("utf-8")).hexdigest()
    payload_hash = command_payload_hash(payload)
    active_states = {"queued", "preparing", "waking", "reconnecting", "executing", "running", "confirming"}

    row = cached_command(request_hash)
    if row is None:
        try:
            with command_db(0.35) as db:
                persisted = db.execute(
                    "SELECT payload_hash,status,response_json,created_at,updated_at,expires_at FROM command_requests WHERE request_hash=?",
                    (request_hash,),
                ).fetchone()
            if persisted is not None:
                row = dict(persisted)
                cache_command(
                    request_hash, str(row.get("payload_hash") or ""), str(row.get("status") or "queued"),
                    str(row.get("response_json") or ""), float(row.get("created_at") or now),
                    float(row.get("updated_at") or now), float(row.get("expires_at") or now + 900),
                )
        except (OSError, sqlite3.Error) as exc:
            LOG.debug("Consulta persistente do diário adiada: %s", exc)

    if row is not None:
        existing_payload_hash = str(row.get("payload_hash") or "")
        if existing_payload_hash and not hmac.compare_digest(existing_payload_hash, payload_hash):
            raise ValueError("O identificador da solicitação já pertence a outro comando.")
        response_raw = str(row.get("response_json") or "")
        if response_raw:
            try:
                response = json.loads(response_raw)
            except (ValueError, TypeError, json.JSONDecodeError):
                response = {}
            if isinstance(response, dict):
                response["duplicate"] = True
                response["request_id"] = request_id
                return None, response
        if str(row.get("status") or "") in active_states and now - float(row.get("updated_at") or 0) < 900:
            return None, {
                "ok": True,
                "accepted": True,
                "queued": True,
                "confirmation_pending": True,
                "duplicate": True,
                "request_id": request_id,
                "status": str(row.get("status") or "queued"),
                "message": "O Gateway já recebeu este comando. A ação não será enviada novamente.",
                "connector_version": connector.CONNECTOR_VERSION,
            }

    created_at = float(row.get("created_at") or now) if row else now
    cache_command(request_hash, payload_hash, "queued", None, created_at, now, now + 900)
    try:
        with command_db(0.75) as db:
            db.execute("DELETE FROM command_requests WHERE expires_at<?", (now,))
            db.execute(
                "INSERT INTO command_requests(request_hash,payload_hash,status,response_json,created_at,updated_at,expires_at) "
                "VALUES(?,?, 'queued',NULL,?,?,?) "
                "ON CONFLICT(request_hash) DO UPDATE SET payload_hash=excluded.payload_hash,status='queued',"
                "response_json=NULL,updated_at=excluded.updated_at,expires_at=excluded.expires_at",
                (request_hash, payload_hash, created_at, now, now + 900),
            )
            db.commit()
    except (OSError, sqlite3.Error) as exc:
        LOG.warning("Diário persistente ocupado; o comando permanece protegido em memória: %s", exc)
    return request_hash, None


def command_journal_progress(
    request_hash: str | None,
    request_id: str,
    status: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if not request_hash:
        return
    allowed = {"queued", "preparing", "waking", "reconnecting", "executing", "confirming"}
    status = status if status in allowed else "executing"
    response: dict[str, Any] = {
        "ok": True,
        "accepted": True,
        "queued": status in {"queued", "preparing"},
        "confirmation_pending": True,
        "status": status,
        "request_id": request_id,
        "message": connector.clean_message(message),
        "connector_version": connector.CONNECTOR_VERSION,
    }
    if isinstance(extra, dict):
        for key in ("attempt", "confirmation_pending"):
            if key in extra:
                response[key] = extra[key]
    raw = json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=connector.json_default)
    now = time.time()
    existing = cached_command(request_hash) or {}
    cache_command(request_hash, str(existing.get("payload_hash") or ""), status, raw, float(existing.get("created_at") or now), now, now + 900)
    try:
        with command_db(0.5) as db:
            db.execute(
                "UPDATE command_requests SET status=?,response_json=?,updated_at=?,expires_at=? WHERE request_hash=?",
                (status, raw[:16000], now, now + 900, request_hash),
            )
            db.commit()
    except (OSError, sqlite3.Error) as exc:
        LOG.warning("Não foi possível atualizar o andamento do comando: %s", exc)


def command_journal_finish(request_hash: str | None, request_id: str, response: dict[str, Any]) -> None:
    if not request_hash:
        return
    safe = dict(response)
    safe["request_id"] = request_id
    final_status = "confirming" if bool(safe.get("confirmation_pending")) else "accepted"
    safe["status"] = final_status
    safe["queued"] = False
    raw = json.dumps(safe, ensure_ascii=False, separators=(",", ":"), default=connector.json_default)
    now = time.time()
    existing = cached_command(request_hash) or {}
    cache_command(request_hash, str(existing.get("payload_hash") or ""), final_status, raw, float(existing.get("created_at") or now), now, now + 900)
    try:
        with command_db(0.5) as db:
            db.execute(
                "UPDATE command_requests SET status=?,response_json=?,updated_at=?,expires_at=? WHERE request_hash=?",
                (final_status, raw[:16000], now, now + 900, request_hash),
            )
            db.commit()
    except (OSError, sqlite3.Error) as exc:
        LOG.warning("Não foi possível concluir o diário de comandos: %s", exc)


def command_journal_fail(request_hash: str | None, request_id: str, exc: BaseException) -> None:
    if not request_hash:
        return
    message = connector.clean_message(str(exc))
    temporary = isinstance(exc, connector.ConnectorTemporaryError) or connector.is_transient_cloud_error(exc)
    response = {
        "ok": False,
        "status": "failed",
        "temporary": bool(temporary),
        "retry_after_seconds": 12 if temporary else 0,
        "request_id": request_id,
        "message": message or "Não foi possível executar o comando remoto.",
        "connector_version": connector.CONNECTOR_VERSION,
    }
    raw = json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=connector.json_default)
    now = time.time()
    existing = cached_command(request_hash) or {}
    cache_command(request_hash, str(existing.get("payload_hash") or ""), "failed", raw, float(existing.get("created_at") or now), now, now + 900)
    try:
        with command_db(0.5) as db:
            db.execute(
                "UPDATE command_requests SET status='failed',response_json=?,updated_at=?,expires_at=? WHERE request_hash=?",
                (raw[:16000], now, now + 900, request_hash),
            )
            db.commit()
    except (OSError, sqlite3.Error) as db_exc:
        LOG.warning("Não foi possível registrar a falha do comando: %s", db_exc)


def command_journal_status(environment: str, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = request_identifier(payload)
    if not request_id:
        raise ValueError("Identificador do comando ausente.")
    request_hash = hashlib.sha256(f"{environment}|{request_id}".encode("utf-8")).hexdigest()
    row = cached_command(request_hash)
    if row is None:
        try:
            with command_db(0.3) as db:
                persisted = db.execute(
                    "SELECT payload_hash,status,response_json,created_at,updated_at,expires_at FROM command_requests WHERE request_hash=?",
                    (request_hash,),
                ).fetchone()
            if persisted is not None:
                row = dict(persisted)
                cache_command(
                    request_hash, str(row.get("payload_hash") or ""), str(row.get("status") or "queued"),
                    str(row.get("response_json") or ""), float(row.get("created_at") or time.time()),
                    float(row.get("updated_at") or time.time()), float(row.get("expires_at") or time.time() + 900),
                )
        except (OSError, sqlite3.Error) as exc:
            raise connector.ConnectorTemporaryError("O diário de comandos está ocupado. A consulta será repetida sem reenviar a ação.") from exc
    if row is None:
        return {
            "ok": False,
            "status": "unknown",
            "request_id": request_id,
            "message": "O Gateway ainda não localizou este comando.",
        }
    response: dict[str, Any] = {}
    raw = str(row.get("response_json") or "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                response = parsed
        except (ValueError, TypeError, json.JSONDecodeError):
            response = {}
    status = str(row.get("status") or "queued")
    active_states = {"queued", "preparing", "waking", "reconnecting", "executing", "running"}
    if status in active_states and time.time() - float(row.get("updated_at") or 0) > 120:
        stale_message = "O Gateway reiniciou ou perdeu o worker antes de concluir este comando. A ação não será repetida automaticamente."
        stale_response = {
            "ok": False,
            "status": "failed",
            "temporary": True,
            "retry_after_seconds": 3,
            "request_id": request_id,
            "message": stale_message,
            "connector_version": connector.CONNECTOR_VERSION,
        }
        raw_stale = json.dumps(stale_response, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        cache_command(request_hash, str(row.get("payload_hash") or ""), "failed", raw_stale, float(row.get("created_at") or now), now, now + 900)
        try:
            with command_db(0.3) as db:
                db.execute(
                    "UPDATE command_requests SET status='failed',response_json=?,updated_at=?,expires_at=? WHERE request_hash=?",
                    (raw_stale, now, now + 900, request_hash),
                )
                db.commit()
        except (OSError, sqlite3.Error):
            pass
        return stale_response
    response.setdefault("ok", status != "failed")
    response["status"] = status
    response["request_id"] = request_id
    response["updated_at"] = float(row.get("updated_at") or 0)
    if status in active_states:
        response.setdefault("accepted", True)
        response.setdefault("queued", status in {"queued", "preparing"})
        response.setdefault("confirmation_pending", True)
        messages = {
            "queued": "Comando recebido e protegido contra repetição.",
            "preparing": "Preparando uma conexão exclusiva para a ação.",
            "waking": "Veículo em repouso. Solicitando despertar.",
            "reconnecting": "Veículo acordando. Refazendo a conexão antes da ação.",
            "executing": "Enviando a ação ao veículo.",
            "running": "Executando o comando remoto.",
        }
        response.setdefault("message", messages.get(status, "Acompanhando a execução do comando."))
    elif status in {"accepted", "confirming"}:
        response.setdefault("accepted", True)
        response.setdefault("queued", False)
        response.setdefault("confirmation_pending", True)
        response.setdefault("message", "Ação enviada. Aguardando a telemetria confirmar o novo estado.")
    return response


def command_worker_key(environment: str, request_id: str) -> str:
    return hashlib.sha256(f"{environment}|{request_id}".encode("utf-8")).hexdigest()


def run_command_job(
    environment: str,
    payload: dict[str, Any],
    request_hash: str | None,
    request_id: str,
    pending_key: str,
) -> None:
    acquired = False
    account_acquired = False
    account_lock: threading.Lock | None = None
    worker_key = command_worker_key(environment, request_id)
    defer_seconds = 4
    try:
        command_journal_progress(request_hash, request_id, "preparing", "Aguardando uma vaga exclusiva para o comando.")
        acquired = SEMAPHORE.acquire(timeout=max(60, MANUAL_WAIT_SECONDS))
        if not acquired:
            raise connector.ConnectorTemporaryError("Conector ocupado. O comando permaneceu protegido e não foi repetido.")
        account_lock = account_operation_lock(environment, payload)
        account_acquired = account_lock.acquire(timeout=max(60, MANUAL_WAIT_SECONDS))
        if not account_acquired:
            raise connector.ConnectorTemporaryError("A conta ainda finalizava uma leitura anterior. Tente novamente em instantes.")
        TELEMETRY.invalidate_account_session(environment, payload)

        def progress(stage: str, message: str, extra: dict[str, Any] | None = None) -> None:
            command_journal_progress(request_hash, request_id, stage, message, extra)

        result = connector.handle_command(payload, progress=progress)
        if request_id:
            result["request_id"] = request_id
        result["queued"] = False
        command_journal_finish(request_hash, request_id, result)
        defer_seconds = 5 if bool(result.get("wake_attempted")) else 3
        LOG.info(
            "Comando remoto %s enviado em segundo plano para %s; confirmação pela telemetria=%s.",
            str(payload.get("command") or "desconhecido")[:40],
            environment,
            bool(result.get("confirmation_pending") or result.get("verification_requested")),
        )
    except BaseException as exc:  # noqa: BLE001
        command_journal_fail(request_hash, request_id, exc)
        defer_seconds = 3
        LOG.warning("Comando remoto em segundo plano falhou (%s): %s", type(exc).__name__, connector.clean_message(str(exc)))
    finally:
        manual_operation_defer(pending_key, defer_seconds)
        if account_acquired and account_lock is not None:
            account_lock.release()
        if acquired:
            SEMAPHORE.release()
        manual_operation_leave(pending_key)
        # A janela de telemetria já foi criada pelo Leap Hub. Despertar o worker
        # logo após o pequeno intervalo evita esperar o ciclo normal do carro.
        timer = threading.Timer(float(defer_seconds) + 0.2, TELEMETRY.wake_event.set)
        timer.daemon = True
        timer.start()
        with COMMAND_WORKERS_GUARD:
            COMMAND_WORKERS.pop(worker_key, None)


def start_command_job(
    environment: str, payload: dict[str, Any], request_hash: str | None, request_id: str
) -> bool:
    if not request_hash or not request_id:
        return False
    worker_key = command_worker_key(environment, request_id)
    with COMMAND_WORKERS_GUARD:
        existing = COMMAND_WORKERS.get(worker_key)
        if existing is not None and existing.is_alive():
            return True
        pending_key = manual_operation_enter(environment, payload)
        worker = threading.Thread(
            target=run_command_job,
            args=(environment, dict(payload), request_hash, request_id, pending_key),
            name=f"leaphub-command-{request_id[:8]}",
            daemon=True,
        )
        COMMAND_WORKERS[worker_key] = worker
        worker.start()
    return True


def command_journal_abort(request_hash: str | None) -> None:
    if not request_hash:
        return
    with COMMAND_CACHE_LOCK:
        COMMAND_CACHE.pop(request_hash, None)
    try:
        with command_db(0.3) as db:
            db.execute("DELETE FROM command_requests WHERE request_hash=?", (request_hash,))
            db.commit()
    except (OSError, sqlite3.Error):
        pass


def cleanup_nonces(now: float) -> None:
    expired = [key for key, created in NONCES.items() if created < now - WINDOW_SECONDS]
    for key in expired:
        NONCES.pop(key, None)


def initialize_nonce_db() -> None:
    NONCE_DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sqlite3.connect(NONCE_DB_PATH, timeout=10.0) as db:
        db.execute("PRAGMA busy_timeout = 10000")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA synchronous = NORMAL")
        db.execute("CREATE TABLE IF NOT EXISTS connector_nonces (nonce_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_connector_nonces_expiry ON connector_nonces(expires_at)")
        db.commit()
    _chmod_private(NONCE_DB_PATH)


def remember_nonce(environment: str, nonce: str, now: float) -> None:
    """Reject replay immediately in memory and persist without blocking request traffic."""
    global NONCE_DB_LAST_CLEANUP, NONCE_DB_LAST_WARNING
    nonce_key = environment + ":" + nonce
    with NONCE_LOCK:
        cleanup_nonces(now)
        if nonce_key in NONCES:
            raise PermissionError("Requisição repetida.")
        NONCES[nonce_key] = now

    nonce_hash = hashlib.sha256(f"{environment}|{nonce}".encode("utf-8")).hexdigest()
    expires_at = now + WINDOW_SECONDS + 30
    try:
        with NONCE_DB_LOCK, sqlite3.connect(NONCE_DB_PATH, timeout=0.2) as db:
            db.execute("PRAGMA busy_timeout = 200")
            db.execute("PRAGMA synchronous = NORMAL")
            if now - NONCE_DB_LAST_CLEANUP >= 60:
                db.execute("DELETE FROM connector_nonces WHERE expires_at < ?", (now,))
                NONCE_DB_LAST_CLEANUP = now
            try:
                db.execute("INSERT INTO connector_nonces (nonce_hash, expires_at) VALUES (?, ?)", (nonce_hash, expires_at))
            except sqlite3.IntegrityError as exc:
                with NONCE_LOCK:
                    NONCES.pop(nonce_key, None)
                raise PermissionError("Requisição repetida.") from exc
            db.commit()
    except PermissionError:
        raise
    except (OSError, sqlite3.Error) as exc:
        if now - NONCE_DB_LAST_WARNING >= 60:
            NONCE_DB_LAST_WARNING = now
            LOG.warning("Proteção persistente de nonce ocupada; proteção imediata em memória permanece ativa: %s", exc)


def verify_signature(method: str, path: str, body: bytes, headers: Any) -> str:
    timestamp = str(headers.get("X-LeapHub-Timestamp") or "").strip()
    nonce = str(headers.get("X-LeapHub-Nonce") or "").strip()
    environment = str(headers.get("X-LeapHub-Environment") or "").strip().lower()
    signature = str(headers.get("X-LeapHub-Signature") or "").strip().lower()
    if environment not in SECRETS or len(SECRETS[environment]) < 32:
        raise PermissionError("Ambiente não configurado no App.")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > WINDOW_SECONDS:
        raise PermissionError("Assinatura expirada.")
    if re.fullmatch(r"[a-f0-9]{32,128}", nonce) is None:
        raise PermissionError("Nonce inválido.")
    if re.fullmatch(r"[a-f0-9]{64}", signature) is None:
        raise PermissionError("Assinatura ausente.")
    now = time.time()
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}".encode("utf-8")
    expected = hmac.new(SECRETS[environment].encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PermissionError("Assinatura inválida.")
    remember_nonce(environment, nonce, now)
    return environment


def account_operation_key(environment: str, payload: dict[str, Any]) -> str:
    credentials = payload.get("credentials") if isinstance(payload.get("credentials"), dict) else payload
    email = str(credentials.get("email") or "").strip().lower() if isinstance(credentials, dict) else ""
    stable = email or str(payload.get("account_id") or payload.get("vehicle_id") or "anonymous")
    return hashlib.sha256(f"{environment}|{stable}".encode("utf-8")).hexdigest()


def account_operation_lock(environment: str, payload: dict[str, Any]) -> threading.Lock:
    key = account_operation_key(environment, payload)
    now = time.time()
    with ACCOUNT_LOCKS_GUARD:
        if len(ACCOUNT_LOCKS) > 1024:
            stale = [
                item_key for item_key, used_at in ACCOUNT_LOCK_LAST_USED.items()
                if used_at < now - 3600 and not ACCOUNT_LOCKS.get(item_key, threading.Lock()).locked()
            ]
            for item_key in stale[:256]:
                ACCOUNT_LOCKS.pop(item_key, None)
                ACCOUNT_LOCK_LAST_USED.pop(item_key, None)
        lock = ACCOUNT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            ACCOUNT_LOCKS[key] = lock
        ACCOUNT_LOCK_LAST_USED[key] = now
        return lock


def manual_operation_enter(environment: str, payload: dict[str, Any]) -> str:
    key = account_operation_key(environment, payload)
    with MANUAL_PENDING_GUARD:
        MANUAL_PENDING[key] = MANUAL_PENDING.get(key, 0) + 1
    return key


def manual_operation_leave(key: str) -> None:
    with MANUAL_PENDING_GUARD:
        remaining = MANUAL_PENDING.get(key, 0) - 1
        if remaining > 0:
            MANUAL_PENDING[key] = remaining
        else:
            MANUAL_PENDING.pop(key, None)


def manual_operation_defer(key: str, seconds: int = 12) -> None:
    if not key:
        return
    with MANUAL_PENDING_GUARD:
        MANUAL_DEFER_UNTIL[key] = max(MANUAL_DEFER_UNTIL.get(key, 0.0), time.time() + max(2, min(45, int(seconds))))


def manual_operation_pending(environment: str, payload: dict[str, Any]) -> bool:
    key = account_operation_key(environment, payload)
    now = time.time()
    with MANUAL_PENDING_GUARD:
        expired = [item for item, until in MANUAL_DEFER_UNTIL.items() if until <= now]
        for item in expired:
            MANUAL_DEFER_UNTIL.pop(item, None)
        return MANUAL_PENDING.get(key, 0) > 0 or MANUAL_DEFER_UNTIL.get(key, 0.0) > now


# A telemetria e as operações manuais usam o mesmo lock por conta. Isso impede
# que uma leitura automática e uma sincronização manual façam login em paralelo.
TELEMETRY = TelemetryEngine(
    OPTIONS,
    SECRETS,
    SEMAPHORE,
    account_lock_provider=account_operation_lock,
    account_wait_seconds=MANUAL_WAIT_SECONDS,
    manual_pending_provider=manual_operation_pending,
)


def connector_ready() -> bool:
    return connector.package_version() is not None and any(len(secret) >= 32 for secret in SECRETS.values())


def public_health_payload() -> dict[str, Any]:
    return {"ok": connector_ready()}


def detailed_health_payload(environment: str) -> dict[str, Any]:
    library = connector.package_version()
    configured = [name for name, secret in SECRETS.items() if len(secret) >= 32]
    return {
        "ok": library is not None and environment in configured,
        "service": SERVICE,
        "message": "Conector remoto pronto." if library is not None and environment in configured else "Confira a chave do ambiente e a biblioteca leapmotor-api.",
        "version": VERSION,
        "connector_version": connector.CONNECTOR_VERSION,
        "library_version": library,
        "python_version": sys.version.split()[0],
        "environment": environment,
        "configured_environments": configured,
        "telemetry_storage": TELEMETRY.storage_status(),
        "uptime_seconds": int(time.time() - STARTED_AT),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "LeapHubConnector"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15.0)

    def log_message(self, fmt: str, *args: Any) -> None:
        line = fmt % args
        if self.client_address[0] in {"127.0.0.1", "::1"}:
            if 'GET /health ' in line and line.endswith(' 200 -'):
                LOG.debug("local healthcheck")
                return
            if 'POST /v1/telemetry/subscriptions/boost ' in line and line.endswith(' 200 -'):
                LOG.debug("local telemetry boost")
                return
        LOG.info("%s - %s", self.address_string(), line)

    def send_json(self, status: int, payload: dict[str, Any]) -> bool:
        body = json_bytes(payload)
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Connection", "close")
            retry_after = int(payload.get("retry_after_seconds") or 0) if isinstance(payload, dict) else 0
            if retry_after > 0:
                self.send_header("Retry-After", str(min(86400, retry_after)))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, TimeoutError) as exc:
            self.close_connection = True
            LOG.debug("Cliente encerrou a resposta antes do fim: %s", exc)
            return False
        except OSError as exc:
            if exc.errno in {errno.EPIPE, errno.ECONNRESET, errno.ETIMEDOUT, errno.EBADF}:
                self.close_connection = True
                LOG.debug("Transporte encerrado durante a resposta: %s", exc)
                return False
            raise

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self.send_json(200, public_health_payload())
            return
        if path in {"/health/details", "/v1/telemetry/status"}:
            try:
                environment = verify_signature("GET", path, b"", self.headers)
            except PermissionError as exc:
                LOG.warning("Private diagnostics rejected: %s", exc)
                self.send_json(403, {"ok": False})
                return
            if path == "/health/details":
                details = detailed_health_payload(environment)
                details["telemetry"] = TELEMETRY.status_fast()
                self.send_json(200, details)
            else:
                self.send_json(200, TELEMETRY.status())
            return
        self.send_json(404, {"ok": False, "message": "Página não encontrada."})

    def do_POST(self) -> None:
        if self.path not in {"/v1/accounts/test", "/v1/vehicles/sync", "/v1/vehicles/command", "/v1/vehicles/command/status", "/v1/telemetry/subscriptions/upsert", "/v1/telemetry/subscriptions/remove", "/v1/telemetry/subscriptions/boost", "/v1/telemetry/subscriptions/release"}:
            self.send_json(404, {"ok": False, "message": "Página não encontrada."})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self.send_json(413, {"ok": False, "message": "Payload inválido."})
            return
        body = self.rfile.read(length)
        try:
            environment = verify_signature("POST", self.path, body, self.headers)
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Payload inválido.")
        except PermissionError as exc:
            LOG.warning("Request rejected: %s", exc)
            self.send_json(403, {"ok": False, "message": "Requisição recusada."})
            return
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "message": "Payload inválido."})
            return

        request_id = request_identifier(payload)
        command_journal_key: str | None = None

        try:
            if self.path in {"/v1/telemetry/subscriptions/boost", "/v1/telemetry/subscriptions/release"}:
                LOG.debug("Action %s accepted for %s", self.path, environment)
            else:
                LOG.info("Action %s accepted for %s", self.path, environment)
            if self.path == "/v1/telemetry/subscriptions/upsert":
                self.send_json(200, TELEMETRY.upsert(environment, payload))
                return
            if self.path == "/v1/telemetry/subscriptions/remove":
                self.send_json(200, TELEMETRY.remove(str(payload.get("subscription_id") or "")))
                return
            if self.path == "/v1/telemetry/subscriptions/boost":
                self.send_json(200, TELEMETRY.boost(
                    str(payload.get("subscription_id") or ""),
                    int(payload.get("seconds") or 900),
                    str(payload.get("profile") or "background"),
                    payload.get("context") if isinstance(payload.get("context"), dict) else {},
                ))
                return
            if self.path == "/v1/telemetry/subscriptions/release":
                self.send_json(200, TELEMETRY.release_interactive(
                    str(payload.get("subscription_id") or ""),
                ))
                return
            if self.path == "/v1/vehicles/command/status":
                self.send_json(200, command_journal_status(environment, payload))
                return
            if self.path == "/v1/vehicles/command":
                command_journal_key, replay = command_journal_begin(environment, payload)
                if replay is not None:
                    self.send_json(200, replay)
                    return
                if command_journal_key is not None and request_id and start_command_job(
                    environment, payload, command_journal_key, request_id
                ):
                    self.send_json(200, {
                        "ok": True,
                        "accepted": True,
                        "queued": True,
                        "status": "queued",
                        "confirmation_pending": True,
                        "request_id": request_id,
                        "message": "Comando recebido e protegido. Preparando a execução sem bloquear a tela.",
                        "connector_version": connector.CONNECTOR_VERSION,
                    })
                    return
            pending_key = manual_operation_enter(environment, payload)
            acquired = False
            account_acquired = False
            account_lock: threading.Lock | None = None
            try:
                acquired = SEMAPHORE.acquire(timeout=MANUAL_WAIT_SECONDS)
                if not acquired:
                    self.send_json(503, {"ok": False, "temporary": True, "retry_after_seconds": 3, "message": "Conector ocupado. A telemetria automática cedeu prioridade; tente novamente em instantes."})
                    return
                account_lock = account_operation_lock(environment, payload)
                account_acquired = account_lock.acquire(timeout=MANUAL_WAIT_SECONDS)
                if not account_acquired:
                    self.send_json(503, {
                        "ok": False,
                        "temporary": True,
                        "retry_after_seconds": 3,
                        "message": "Finalizando uma leitura já iniciada desta conta. O comando continua com prioridade.",
                    })
                    return
                if self.path == "/v1/accounts/test":
                    result = connector.handle_account(payload, sync=False)
                elif self.path == "/v1/vehicles/sync":
                    result = connector.handle_account(payload, sync=True)
                else:
                    # Fallback síncrono para clientes antigos sem request_id.
                    # Clientes atuais entram na fila protegida e recebem resposta imediata.
                    if command_journal_key is None:
                        command_journal_key, replay = command_journal_begin(environment, payload)
                        if replay is not None:
                            self.send_json(200, replay)
                            return
                    TELEMETRY.invalidate_account_session(environment, payload)
                    try:
                        result = connector.handle_command(payload)
                        if request_id:
                            result["request_id"] = request_id
                        command_journal_finish(command_journal_key, request_id, result)
                    except Exception:
                        command_journal_abort(command_journal_key)
                        raise
                    finally:
                        # A nuvem frequentemente invalida o token de leitura logo
                        # após uma operação remota. Aguarde a estabilização antes
                        # de criar a próxima sessão automática.
                        manual_operation_defer(pending_key, 12)
                self.send_json(200, result)
            finally:
                if account_acquired and account_lock is not None:
                    account_lock.release()
                if acquired:
                    SEMAPHORE.release()
                manual_operation_leave(pending_key)
        except sqlite3.OperationalError as exc:
            LOG.warning("Armazenamento local temporariamente ocupado: %s", exc)
            self.send_json(503, {
                "ok": False,
                "temporary": True,
                "retry_after_seconds": 2,
                "message": "O Gateway está concluindo uma gravação local. A solicitação pode ser repetida sem duplicar ações.",
                "connector_version": connector.CONNECTOR_VERSION,
            })
        except connector.ConnectorTemporaryError as exc:
            LOG.warning("Reconexão automática adiada: %s", connector.clean_message(str(exc)))
            self.send_json(503, {
                "ok": False,
                "temporary": True,
                "retry_after_seconds": 20,
                "message": connector.clean_message(str(exc)),
                "connector_version": connector.CONNECTOR_VERSION,
            })
        except connector.ConnectorAuthenticationError as exc:
            LOG.warning("Reautenticação recusada pela conta Leapmotor.")
            self.send_json(401, {
                "ok": False,
                "temporary": False,
                "auth_required": True,
                "message": connector.clean_message(str(exc)),
                "connector_version": connector.CONNECTOR_VERSION,
            })
        except (ValueError, RuntimeError) as exc:
            safe_message = connector.clean_message(str(exc))
            command_name = str(payload.get("command") or "")[:80] if isinstance(payload, dict) else ""
            LOG.warning("Comando remoto %s recusado (%s): %s", command_name or "desconhecido", type(exc).__name__, safe_message)
            self.send_json(422, {"ok": False, "message": safe_message, "connector_version": connector.CONNECTOR_VERSION})
        except Exception as exc:  # noqa: BLE001
            if connector.is_transient_cloud_error(exc):
                LOG.warning("Falha temporária recuperável não classificada: %s", connector.clean_message(str(exc)))
                self.send_json(503, {
                    "ok": False,
                    "temporary": True,
                    "retry_after_seconds": 20,
                    "message": connector.reconnect_message(exc),
                    "connector_version": connector.CONNECTOR_VERSION,
                })
                return
            LOG.exception("Unhandled connector error")
            self.send_json(500, {"ok": False, "message": "Falha interna no conector.", "connector_version": connector.CONNECTOR_VERSION})


class ConnectorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


if __name__ == "__main__":
    if not any(len(secret) >= 32 for secret in SECRETS.values()):
        LOG.error("Configure staging_secret ou production_secret antes de iniciar.")
    initialize_command_db()
    initialize_nonce_db()
    server = ConnectorHTTPServer(("0.0.0.0", 8094), Handler)
    TELEMETRY.start()
    LOG.info("%s listening on port 8094", SERVICE)
    try:
        server.serve_forever()
    finally:
        TELEMETRY.stop()
