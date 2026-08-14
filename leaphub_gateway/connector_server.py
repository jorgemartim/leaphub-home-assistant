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

try:
    from leaphub_privacy import install_logging_privacy_filter
except ModuleNotFoundError:
    from privacy import install_logging_privacy_filter
try:
    from leaphub_connection_orchestrator import ORCHESTRATOR
except ModuleNotFoundError:
    try:
        from connection_orchestrator import ORCHESTRATOR
    except ModuleNotFoundError:
        import importlib.util as _importlib_util
        _orchestrator_path = Path(__file__).with_name("connection_orchestrator.py")
        _orchestrator_spec = _importlib_util.spec_from_file_location("leaphub_connection_orchestrator_local", _orchestrator_path)
        if _orchestrator_spec is None or _orchestrator_spec.loader is None:
            raise
        _orchestrator_module = _importlib_util.module_from_spec(_orchestrator_spec)
        _orchestrator_spec.loader.exec_module(_orchestrator_module)
        ORCHESTRATOR = _orchestrator_module.ORCHESTRATOR
try:
    from leaphub_event_transport import EVENT_TRANSPORT
except ModuleNotFoundError:
    try:
        from event_transport import EVENT_TRANSPORT
    except ModuleNotFoundError:
        import importlib.util as _event_importlib_util
        _event_transport_path = Path(__file__).with_name("event_transport.py")
        _event_transport_spec = _event_importlib_util.spec_from_file_location("leaphub_event_transport_local", _event_transport_path)
        if _event_transport_spec is None or _event_transport_spec.loader is None:
            raise
        _event_transport_module = _event_importlib_util.module_from_spec(_event_transport_spec)
        _event_transport_spec.loader.exec_module(_event_transport_module)
        EVENT_TRANSPORT = _event_transport_module.EVENT_TRANSPORT

VERSION = "1.12.95"
API_VERSION = 2
CAPABILITY_SCHEMA_VERSION = 1
MIN_SUPPORTED_CLIENT_API_VERSION = 1
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
MANAGER_STATUS_PATH = Path(os.getenv("LEAPHUB_MANAGER_STATUS_PATH", "/data/runtime/unified-status.json"))
COMMAND_CACHE: dict[str, dict[str, Any]] = {}
COMMAND_CACHE_LOCK = threading.RLock()
COMMAND_CACHE_MAX = 2000
COMMAND_CANCEL_REQUESTS: set[str] = set()
MAX_AUTH_RETRY_SECONDS = 1800
AUTH_RETRY_CLOCK_SKEW_SECONDS = 90


class CommandCancelled(RuntimeError):
    """Internal control flow for requests cancelled before cloud dispatch."""


class PriorityOperationLimiter:
    """Limite global com prioridade para comandos manuais.

    Cada conta continua com sua própria trava. Este limitador apenas protege os
    recursos totais do add-on e impede a telemetria de ocupar todas as vagas
    quando há comandos de usuários aguardando.
    """

    def __init__(self, capacity: int) -> None:
        self.capacity = max(1, int(capacity))
        self._active = 0
        self._manual_waiters = 0
        self._background_waiters = 0
        self._condition = threading.Condition()

    def acquire(self, blocking: bool = True, timeout: float = -1, priority: bool = False) -> bool:
        deadline = None if timeout is None or timeout < 0 else time.monotonic() + float(timeout)
        with self._condition:
            if priority:
                self._manual_waiters += 1
            else:
                self._background_waiters += 1
            try:
                while self._active >= self.capacity or (not priority and self._manual_waiters > 0):
                    if not blocking:
                        return False
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        return False
                    self._condition.wait(remaining)
                self._active += 1
                return True
            finally:
                if priority:
                    self._manual_waiters = max(0, self._manual_waiters - 1)
                else:
                    self._background_waiters = max(0, self._background_waiters - 1)
                self._condition.notify_all()

    def release(self) -> None:
        with self._condition:
            if self._active <= 0:
                raise ValueError("Operation limiter released too many times")
            self._active -= 1
            self._condition.notify_all()

    def snapshot(self) -> dict[str, int]:
        with self._condition:
            return {
                "capacity": self.capacity,
                "active": self._active,
                "manual_waiters": self._manual_waiters,
                "background_waiters": self._background_waiters,
            }


class AccountOperationLock:
    """Lock por conta com diagnóstico seguro do ocupante atual.

    A trava não armazena e-mail, VIN, PIN ou qualquer credencial. O metadado é
    usado apenas para distinguir telemetria, comando e manutenção nos logs.
    """

    def __init__(self, key: str) -> None:
        self.key = key
        self._lock = threading.Lock()
        self._meta_lock = threading.Lock()
        self._owner = ""
        self._acquired_at = 0.0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if timeout is None or timeout < 0:
            acquired = self._lock.acquire(blocking)
        else:
            acquired = self._lock.acquire(blocking, timeout)
        if acquired:
            with self._meta_lock:
                self._owner = threading.current_thread().name[:80]
                self._acquired_at = time.monotonic()
        return acquired

    def release(self) -> None:
        with self._meta_lock:
            self._owner = ""
            self._acquired_at = 0.0
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()

    def snapshot(self) -> dict[str, Any]:
        with self._meta_lock:
            held_for = max(0.0, time.monotonic() - self._acquired_at) if self._acquired_at else 0.0
            return {"owner": self._owner, "held_for_seconds": round(held_for, 1)}


ACCOUNT_LOCKS: dict[str, AccountOperationLock] = {}
ACCOUNT_LOCK_LAST_USED: dict[str, float] = {}
ACCOUNT_LOCKS_GUARD = threading.Lock()
MANUAL_PENDING: dict[str, int] = {}
MANUAL_DEFER_UNTIL: dict[str, float] = {}
MANUAL_PENDING_GUARD = threading.Lock()
COMMAND_WORKERS: dict[str, threading.Thread] = {}
COMMAND_RETRY_TIMERS: dict[str, threading.Timer] = {}
COMMAND_WORKERS_GUARD = threading.Lock()
SYNC_WORKERS: dict[str, threading.Thread] = {}
SYNC_WORKERS_GUARD = threading.Lock()
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
SEMAPHORE = PriorityOperationLimiter(MAX_PARALLEL)
MANUAL_WAIT_SECONDS = max(2, min(60, int(OPTIONS.get("connector_manual_wait_seconds") or OPTIONS.get("manual_wait_seconds") or 35)))
MANUAL_QUEUE_SECONDS = max(120, min(300, int(OPTIONS.get("connector_manual_queue_seconds") or 180)))
MANUAL_SETTLE_SECONDS = max(8, min(45, int(OPTIONS.get("connector_manual_settle_seconds") or 20)))
LOG_LEVEL = str(OPTIONS.get("log_level") or "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
install_logging_privacy_filter()
LOG = logging.getLogger("leaphub.connector")
logging.getLogger("leapmotor_api").setLevel(logging.WARNING)
TELEMETRY: TelemetryEngine


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=connector.json_default).encode("utf-8")


def trace_identifier(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9._:-]{7,95}", candidate):
        return candidate
    return hashlib.sha256(f"{time.time_ns()}:{threading.get_ident()}".encode("utf-8")).hexdigest()[:24]


def client_api_version(headers: Any) -> int:
    raw = str(headers.get("X-LeapHub-API-Version") or "1").strip()
    try:
        return int(raw)
    except ValueError:
        return 0


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
    active_states = {"queued", "waiting_auth", "waiting_account", "waiting_slot", "preparing", "waking", "vehicle_waking", "vehicle_awake", "reconnecting", "retry_wait", "climate_dispatching", "climate_verifying", "verifying", "executing", "running"}

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
        existing_status = str(row.get("status") or "")
        stale_waiting_auth = False
        if response_raw:
            try:
                response = json.loads(response_raw)
            except (ValueError, TypeError, json.JSONDecodeError):
                response = {}
            if isinstance(response, dict):
                retry_at = float(response.get("retry_at") or 0)
                retry_after = int(response.get("retry_after_seconds") or 0)
                impossible_waiting_auth = existing_status == "waiting_auth" and (
                    retry_after < 0
                    or retry_after > MAX_AUTH_RETRY_SECONDS
                    or retry_at > now + MAX_AUTH_RETRY_SECONDS + AUTH_RETRY_CLOCK_SKEW_SECONDS
                )
                if existing_status == "waiting_auth" and not impossible_waiting_auth:
                    # Backoffs progressivos legítimos chegam a 30 minutos. Antes
                    # da 1.12.15.1 qualquer espera acima de 5 minutos era tratada
                    # como registro defeituoso, o que podia reenviar o comando e
                    # renovar o bloqueio da Leapmotor antes da hora.
                    if retry_at > now:
                        response["retry_after_seconds"] = max(1, int(retry_at - now))
                        response["duplicate"] = True
                        response["request_id"] = request_id
                        return None, response
                    try:
                        auth_status = TELEMETRY.account_auth_status(environment, payload)
                    except Exception as exc:  # noqa: BLE001
                        LOG.debug("Consulta do cooldown global adiada para o comando %s: %s", request_id[:12], exc)
                        auth_status = {"cooldown": True, "retry_after_seconds": 30}
                    if bool(auth_status.get("cooldown")):
                        remaining = max(1, min(MAX_AUTH_RETRY_SECONDS, int(auth_status.get("retry_after_seconds") or 30)))
                        response["retry_after_seconds"] = remaining
                        response["retry_at"] = now + remaining
                        response["duplicate"] = True
                        response["request_id"] = request_id
                        response["message"] = "A autenticação global ainda está protegida. O comando permanece na fila sem novo envio."
                        return None, response
                    stale_waiting_auth = True
                elif impossible_waiting_auth:
                    # Um registro realmente impossível é retomado apenas depois
                    # de confirmar que o coordenador global não está bloqueado.
                    try:
                        auth_status = TELEMETRY.account_auth_status(environment, payload)
                    except Exception:  # noqa: BLE001
                        auth_status = {"cooldown": True}
                    if bool(auth_status.get("cooldown")):
                        response["duplicate"] = True
                        response["request_id"] = request_id
                        return None, response
                    stale_waiting_auth = True
                else:
                    response["duplicate"] = True
                    response["request_id"] = request_id
                    return None, response
        if stale_waiting_auth:
            LOG.info("Retomando o comando %s somente após o coordenador global liberar a autenticação.", request_id[:12])
            row["status"] = "queued"
            row["response_json"] = ""
        if str(row.get("status") or "") in active_states and now - float(row.get("updated_at") or 0) < 900 and not stale_waiting_auth:
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
    allowed = {"queued", "waiting_auth", "waiting_account", "waiting_slot", "preparing", "waking", "vehicle_waking", "vehicle_awake", "reconnecting", "retry_wait", "climate_dispatching", "climate_verifying", "verifying", "executing"}
    status = status if status in allowed else "executing"
    response: dict[str, Any] = {
        "ok": True,
        "accepted": True,
        "queued": status in {"queued", "waiting_auth", "waiting_account", "waiting_slot", "preparing"},
        "confirmation_pending": True,
        "status": status,
        "request_id": request_id,
        "message": connector.clean_message(message),
        "connector_version": connector.CONNECTOR_VERSION,
    }
    if isinstance(extra, dict):
        for key in ("attempt", "confirmation_pending", "verified_by_gateway", "safe_retry", "queue_wait_seconds", "waiting_for", "session_recovery", "retry_after_seconds", "retry_at", "cloud_accepted", "verification_sample", "state_fresh", "state_evaluable"):
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


def command_journal_finish(request_hash: str | None, request_id: str, response: dict[str, Any]) -> dict[str, Any] | None:
    """Fecha o diário do comando e devolve o payload que o site vai ler.

    1.12.78 — o retorno é novo. O anúncio imediato ao site precisa enviar
    EXATAMENTE o mesmo dicionário que `/v1/vehicles/command/status` devolveria,
    senão push e cron passariam a produzir estados diferentes para o mesmo
    comando. Devolvendo `safe` aqui, existe uma única fonte desse payload.
    """
    if not request_hash:
        return None
    safe = dict(response)
    safe["request_id"] = request_id
    # A entrega à nuvem e a aplicação física são resultados diferentes. Uma
    # leitura nova contraditória termina como not_applied e nunca como sent.
    if bool(safe.get("verified_by_gateway")):
        final_status = "completed"
    elif bool(safe.get("not_applied")):
        final_status = "not_applied"
    else:
        final_status = "sent"
    safe["status"] = final_status
    safe["queued"] = False
    safe["ok"] = final_status != "not_applied"
    safe["accepted"] = True
    safe["vehicle_confirmed"] = final_status == "completed"
    safe["confirmation_pending"] = final_status == "sent"
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
    return safe


def announce_command_result_async(environment: str, request_id: str, payload: dict[str, Any] | None) -> None:
    """Anuncia ao site o fim do comando sem segurar o worker.

    1.12.78 — em thread própria porque, neste ponto, o worker ainda precisa
    liberar a trava da conta e a vaga do connector. Um site lento não pode
    atrasar o PRÓXIMO comando do dono: o anúncio é atalho, não etapa. Sem ele,
    nada quebra — só volta a valer o ciclo do cron.
    """
    if not payload or not request_id:
        return

    def _run() -> None:
        try:
            announced = TELEMETRY.announce_command_result(environment, request_id, payload)
            if announced:
                LOG.info("Resultado do comando %s anunciado imediatamente ao site.", str(request_id)[:12])
            else:
                LOG.info("Resultado do comando %s não foi aceito pelo atalho imediato; reconciliação segue pelo ciclo normal.", str(request_id)[:12])
        except Exception as exc:
            LOG.info("Anúncio imediato do comando %s falhou; reconciliação segue pelo ciclo normal: %s", str(request_id)[:12], connector.clean_message(str(exc)))

    try:
        threading.Thread(target=_run, name="leaphub-command-announce", daemon=True).start()
    except RuntimeError as exc:
        # Interpretador em desligamento não aceita thread nova. O comando já
        # está gravado no diário; a reconciliação segue pelo ciclo do cron.
        LOG.debug("Anúncio do comando %s não pôde ser agendado: %s", str(request_id)[:12], exc)


def command_journal_wait_auth(request_hash: str | None, request_id: str, retry_after_seconds: int) -> None:
    if not request_hash:
        return
    delay = max(30, min(1800, int(retry_after_seconds or 300)))
    now = time.time()
    retry_at = now + delay
    response = {
        "ok": True,
        "accepted": True,
        "queued": True,
        "temporary": True,
        "status": "waiting_auth",
        "retry_after_seconds": delay,
        "retry_at": retry_at,
        "resume_required": True,
        "confirmation_pending": True,
        "request_id": request_id,
        "message": "A Leapmotor limitou temporariamente novas autenticações. O comando continuará na fila e será enviado automaticamente.",
        "connector_version": connector.CONNECTOR_VERSION,
    }
    raw = json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=connector.json_default)
    existing = cached_command(request_hash) or {}
    expires_at = max(now + 900, retry_at + 300)
    cache_command(request_hash, str(existing.get("payload_hash") or ""), "waiting_auth", raw, float(existing.get("created_at") or now), now, expires_at)
    try:
        with command_db(0.5) as db:
            db.execute(
                "UPDATE command_requests SET status='waiting_auth',response_json=?,updated_at=?,expires_at=? WHERE request_hash=?",
                (raw[:16000], now, expires_at, request_hash),
            )
            db.commit()
    except (OSError, sqlite3.Error) as exc:
        LOG.warning("Não foi possível persistir a espera de autenticação: %s", exc)


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
    active_states = {"queued", "waiting_auth", "waiting_account", "waiting_slot", "preparing", "waking", "vehicle_waking", "vehicle_awake", "reconnecting", "retry_wait", "climate_dispatching", "climate_verifying", "verifying", "executing", "running"}
    retry_at = float(response.get("retry_at") or 0)
    retry_after_recorded = int(response.get("retry_after_seconds") or 0)
    impossible_waiting_auth = status == "waiting_auth" and (
        retry_after_recorded < 0
        or retry_after_recorded > MAX_AUTH_RETRY_SECONDS
        or retry_at > time.time() + MAX_AUTH_RETRY_SECONDS + AUTH_RETRY_CLOCK_SKEW_SECONDS
    )
    if impossible_waiting_auth:
        response = {
            "ok": False,
            "status": "failed",
            "temporary": True,
            "retry_after_seconds": 1,
            "request_id": request_id,
            "message": "A espera de autenticação da versão anterior foi corrigida. O comando pode ser retomado com segurança.",
            "connector_version": connector.CONNECTOR_VERSION,
            "stale_login_cooldown_repaired": True,
        }
        raw_repaired = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        cache_command(request_hash, str(row.get("payload_hash") or ""), "failed", raw_repaired, float(row.get("created_at") or now), now, now + 900)
        try:
            with command_db(0.3) as db:
                db.execute("UPDATE command_requests SET status='failed',response_json=?,updated_at=?,expires_at=? WHERE request_hash=?", (raw_repaired, now, now + 900, request_hash))
                db.commit()
        except (OSError, sqlite3.Error):
            pass
        return response
    waiting_auth_valid = status == "waiting_auth" and retry_at > time.time() - 180
    if status in active_states and not waiting_auth_valid and time.time() - float(row.get("updated_at") or 0) > 120:
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
    response.setdefault("ok", status not in {"failed", "cancelled"})
    response["status"] = status
    response["request_id"] = request_id
    response["updated_at"] = float(row.get("updated_at") or 0)
    if status in active_states:
        response.setdefault("accepted", True)
        response.setdefault("queued", status in {"queued", "waiting_auth", "waiting_account", "waiting_slot", "preparing"})
        response.setdefault("confirmation_pending", True)
        messages = {
            "queued": "Comando recebido e protegido contra repetição.",
            "waiting_auth": "A Leapmotor limitou temporariamente novas autenticações. O comando continuará na fila.",
            "waiting_account": "Aguardando a leitura atual da conta terminar. O comando está na fila prioritária.",
            "waiting_slot": "Conta liberada. Aguardando uma vaga no Connector.",
            "preparing": "Preparando uma conexão exclusiva para a ação.",
            "waking": "Veículo em repouso. Solicitando despertar.",
            "vehicle_waking": "Acordando o veículo e aguardando uma leitura nova.",
            "vehicle_awake": "Veículo disponível para a próxima etapa.",
            "reconnecting": "Veículo acordando. Refazendo a conexão antes da ação.",
            "retry_wait": "A nuvem demorou a responder. Verificando o estado antes da repetição protegida.",
            "climate_dispatching": "Veículo disponível. Enviando a climatização.",
            "climate_verifying": "Climatização enviada. Verificando o estado real do veículo.",
            "verifying": "Ação recebida pela nuvem. Finalizando a verificação segura.",
            "executing": "Enviando a ação ao veículo.",
            "running": "Executando o comando remoto.",
        }
        if status == "waiting_auth" and retry_at > 0:
            response["retry_after_seconds"] = max(0, int(retry_at - time.time()))
            response["resume_required"] = True
        remaining = max(0, int(response.get("retry_after_seconds") or 0))
        response["poll_after_seconds"] = (
            max(15, min(120, remaining - 3)) if status == "waiting_auth" and remaining > 18 else
            12 if status == "waiting_account" else
            8 if status in {"waiting_slot", "waking", "vehicle_waking", "vehicle_awake", "reconnecting", "retry_wait", "climate_verifying", "verifying", "confirming"} else
            5
        )
        response.setdefault("message", messages.get(status, "Acompanhando a execução do comando."))
    elif status == "cancelled":
        response["ok"] = True
        response["cancelled"] = True
        response["accepted"] = False
        response["queued"] = False
        response["confirmation_pending"] = False
        response.setdefault("message", "Solicitação cancelada antes do envio ao veículo.")
    elif status == "not_applied":
        response["ok"] = False
        response.setdefault("accepted", True)
        response.setdefault("queued", False)
        response.setdefault("command_dispatched", True)
        response.setdefault("cloud_accepted", True)
        response["confirmation_pending"] = False
        response["vehicle_confirmed"] = False
        response["not_applied"] = True
        response.setdefault("message", "A nuvem recebeu o comando, mas o veículo não aplicou o estado solicitado.")
    elif status in {"accepted", "sent", "confirming"}:
        response.setdefault("accepted", True)
        response.setdefault("queued", False)
        response.setdefault("command_dispatched", True)
        response.setdefault("cloud_accepted", True)
        response.setdefault("confirmation_pending", status != "completed")
        response.setdefault("message", "Comando enviado ao veículo. A confirmação do estado continuará em segundo plano.")
    return response


def command_cancel_requested(environment: str, request_id: str) -> bool:
    worker_key = command_worker_key(environment, request_id)
    with COMMAND_WORKERS_GUARD:
        return worker_key in COMMAND_CANCEL_REQUESTS


def command_journal_cancel(environment: str, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = request_identifier(payload)
    if not request_id:
        raise ValueError("Identificador do comando ausente.")
    request_hash = hashlib.sha256(f"{environment}|{request_id}".encode("utf-8")).hexdigest()
    status_payload = command_journal_status(environment, {"request_id": request_id})
    status = str(status_payload.get("status") or "unknown")
    cancellable_states = {"queued", "waiting_auth", "waiting_account", "waiting_slot", "preparing", "reconnecting", "retry_wait"}
    if status == "cancelled":
        return status_payload
    if status not in cancellable_states:
        return {
            "ok": False,
            "cancelled": False,
            "status": status,
            "request_id": request_id,
            "message": "O comando já começou a ser enviado ao veículo e não pode mais ser cancelado.",
            "connector_version": connector.CONNECTOR_VERSION,
        }
    worker_key = command_worker_key(environment, request_id)
    with COMMAND_WORKERS_GUARD:
        COMMAND_CANCEL_REQUESTS.add(worker_key)
        timer = COMMAND_RETRY_TIMERS.pop(worker_key, None)
        if timer is not None:
            timer.cancel()
    response = {
        "ok": True,
        "cancelled": True,
        "accepted": False,
        "queued": False,
        "confirmation_pending": False,
        "status": "cancelled",
        "request_id": request_id,
        "message": "Solicitação cancelada antes do envio ao veículo.",
        "connector_version": connector.CONNECTOR_VERSION,
    }
    raw = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    now = time.time()
    existing = cached_command(request_hash) or {}
    cache_command(request_hash, str(existing.get("payload_hash") or ""), "cancelled", raw, float(existing.get("created_at") or now), now, now + 900)
    try:
        with command_db(0.5) as db:
            db.execute(
                "UPDATE command_requests SET status='cancelled',response_json=?,updated_at=?,expires_at=? WHERE request_hash=?",
                (raw, now, now + 900, request_hash),
            )
            db.commit()
    except (OSError, sqlite3.Error) as exc:
        LOG.warning("Cancelamento persistido apenas em memória: %s", exc)
    TELEMETRY.wake_event.set()
    LOG.info("Comando %s cancelado antes do envio à nuvem.", request_id[:12])
    return response


def command_worker_key(environment: str, request_id: str) -> str:
    return hashlib.sha256(f"{environment}|{request_id}".encode("utf-8")).hexdigest()


def schedule_command_retry(
    environment: str,
    payload: dict[str, Any],
    request_hash: str,
    request_id: str,
    retry_after_seconds: int,
) -> None:
    delay = max(30, min(1800, int(retry_after_seconds or 300)))
    worker_key = command_worker_key(environment, request_id)

    def resume() -> None:
        with COMMAND_WORKERS_GUARD:
            COMMAND_RETRY_TIMERS.pop(worker_key, None)
            cancelled = worker_key in COMMAND_CANCEL_REQUESTS
        if not cancelled:
            start_command_job(environment, payload, request_hash, request_id)

    timer = threading.Timer(float(delay) + 1.0, resume)
    timer.daemon = True
    with COMMAND_WORKERS_GUARD:
        previous = COMMAND_RETRY_TIMERS.pop(worker_key, None)
        if previous is not None:
            previous.cancel()
        COMMAND_RETRY_TIMERS[worker_key] = timer
    timer.start()


def run_command_job(
    environment: str,
    payload: dict[str, Any],
    request_hash: str | None,
    request_id: str,
    pending_key: str,
) -> None:
    acquired = False
    account_acquired = False
    account_lock: AccountOperationLock | None = None
    worker_key = command_worker_key(environment, request_id)
    defer_seconds = 4
    retry_after_seconds = 0
    queue_started = time.monotonic()
    account_acquired_at = queue_started
    slot_acquired_at = queue_started
    execute_started_at = queue_started
    result: dict[str, Any] | None = None
    try:
        def ensure_not_cancelled() -> None:
            if command_cancel_requested(environment, request_id):
                raise CommandCancelled("Solicitação cancelada antes do envio ao veículo.")

        def progress(stage: str, message: str, extra: dict[str, Any] | None = None) -> None:
            command_journal_progress(request_hash, request_id, stage, message, extra)

        # A operação manual entra em estado pendente antes do worker iniciar.
        # Isso impede novas leituras automáticas desta conta. Uma leitura já em
        # andamento termina no próximo ponto seguro e libera a mesma sessão.
        ensure_not_cancelled()
        account_lock = account_operation_lock(environment, payload)
        next_progress_at = 0.0
        next_log_at = 15.0
        progress(
            "waiting_account",
            "Aguardando a leitura atual terminar. O comando está na fila prioritária.",
            {"queue_wait_seconds": 0, "waiting_for": "telemetry_or_account_operation"},
        )
        TELEMETRY.wake_event.set()
        while not account_lock.acquire(timeout=0.5):
            ensure_not_cancelled()
            elapsed = time.monotonic() - queue_started
            TELEMETRY.wake_event.set()
            if elapsed >= next_progress_at:
                holder = account_lock.snapshot()
                owner = str(holder.get("owner") or "").lower()
                waiting_for = "telemetry" if "telemetry" in owner else "account_operation"
                progress(
                    "waiting_account",
                    "Aguardando a leitura atual terminar. O comando está na fila prioritária.",
                    {"queue_wait_seconds": int(elapsed), "waiting_for": waiting_for},
                )
                next_progress_at = elapsed + 2.0
            if elapsed >= next_log_at:
                holder = account_lock.snapshot()
                LOG.info(
                    "Comando %s aguardando conta há %ss; ocupante=%s, ocupado_há=%ss.",
                    request_id[:12],
                    int(elapsed),
                    str(holder.get("owner") or "desconhecido")[:80],
                    int(float(holder.get("held_for_seconds") or 0)),
                )
                next_log_at = elapsed + 15.0
            if elapsed >= MANUAL_QUEUE_SECONDS:
                raise connector.ConnectorTemporaryError(
                    "A leitura anterior excedeu a janela segura. O comando não foi enviado e pode ser tentado novamente."
                )
        account_acquired = True
        account_acquired_at = time.monotonic()
        ensure_not_cancelled()

        progress(
            "waiting_slot",
            "Conta liberada. Aguardando uma vaga no Connector.",
            {"queue_wait_seconds": int(time.monotonic() - queue_started), "waiting_for": "connector_slot"},
        )
        acquired = SEMAPHORE.acquire(timeout=max(30, MANUAL_WAIT_SECONDS), priority=True)
        if not acquired:
            raise connector.ConnectorTemporaryError(
                "A conta foi liberada, mas o Connector permaneceu ocupado. O comando não foi enviado."
            )
        slot_acquired_at = time.monotonic()

        ensure_not_cancelled()
        progress("preparing", "Preparando a sessão autenticada para a ação.")
        ensure_not_cancelled()
        execute_started_at = time.monotonic()
        result = TELEMETRY.execute_command(environment, payload, progress=progress)
        execute_finished_at = time.monotonic()
        phase_latency = result.get("phase_latency_ms") if isinstance(result.get("phase_latency_ms"), dict) else {}
        latency = {
            "account_wait_ms": int(round((account_acquired_at - queue_started) * 1000)),
            "connector_slot_ms": int(round((slot_acquired_at - account_acquired_at) * 1000)),
            "remote_execute_ms": int(round((execute_finished_at - execute_started_at) * 1000)),
            "total_ms": int(round((execute_finished_at - queue_started) * 1000)),
            # 1.12.50 - estas duas fases existiam mas nao eram medidas. Sem elas
            # a soma das fases nao fechava com remote_execute_ms e a maior parte
            # do tempo de um comando ficava invisivel no log.
            "session_wait_ms": int(phase_latency.get("session_wait_ms") or 0),
            "session_login_ms": int(phase_latency.get("session_login_ms") or 0),
            "session_prepare_ms": int(phase_latency.get("session_prepare_ms") or 0),
            "dispatch_ms": int(phase_latency.get("dispatch_ms") or 0),
            "verification_ms": int(phase_latency.get("verification_ms") or 0),
            # 1.12.56 - as tres fases que faltavam para fechar remote_execute_ms.
            # engine_precheck + session_wait + session_login + handle_command +
            # confirmation_arm cobrem o metodo inteiro; progress_ms e a quebra de
            # handle_command para o diario de progresso.
            "engine_precheck_ms": int(phase_latency.get("engine_precheck_ms") or 0),
            # 1.12.56 - a quebra de engine_precheck_ms. Um comando de campo
            # mediu 135718ms nele com todas as demais fases somando ~5s; as
            # tres abaixo dizem qual das partes gastou. Vivem DENTRO de
            # engine_precheck_ms, entao nao entram no calculo de nao atribuido.
            "auth_status_ms": int(phase_latency.get("auth_status_ms") or 0),
            "engine_lock_wait_ms": int(phase_latency.get("engine_lock_wait_ms") or 0),
            "subscription_read_ms": int(phase_latency.get("subscription_read_ms") or 0),
            "handle_command_ms": int(phase_latency.get("handle_command_ms") or 0),
            "post_dispatch_local_ms": int(phase_latency.get("post_dispatch_local_ms") or 0),
            "confirmation_arm_ms": int(phase_latency.get("confirmation_arm_ms") or 0),
            "progress_ms": int(phase_latency.get("progress_ms") or 0),
        }
        # Nomes aditivos e não ambíguos para o painel novo. Os campos legados
        # permanecem porque versões anteriores do site ainda os consomem.
        latency.update({
            "queue_account_ms": latency["account_wait_ms"],
            "queue_connector_ms": latency["connector_slot_ms"],
            "queue_session_ms": latency["session_wait_ms"],
            "remote_login_ms": latency["session_login_ms"],
            "remote_dispatch_ms": latency["dispatch_ms"],
            "remote_result_ms": None,
            "remote_result_bundled_with_dispatch": True,
            "post_state_verify_ms": latency["verification_ms"],
            # 1.12.56 - session_prepare/dispatch/verification/progress vivem
            # DENTRO de handle_command_ms; somá-los aqui contaria duas vezes.
            "unaccounted_ms": max(0, latency["remote_execute_ms"] - (
                latency["engine_precheck_ms"] + latency["session_wait_ms"]
                + latency["session_login_ms"] + latency["handle_command_ms"]
                + latency["post_dispatch_local_ms"] + latency["confirmation_arm_ms"]
            )),
        })
        result["latency"] = latency
        ORCHESTRATOR.record_command_latency(
            environment,
            account_wait_ms=latency["account_wait_ms"],
            connector_slot_ms=latency["connector_slot_ms"],
            remote_execute_ms=latency["remote_execute_ms"],
            total_ms=latency["total_ms"],
            session_prepare_ms=latency["session_prepare_ms"],
            dispatch_ms=latency["dispatch_ms"],
            verification_ms=latency["verification_ms"],
        )
        ORCHESTRATOR.record_cloud_success(
            environment,
            payload.get("account_id") or payload.get("vehicle_id"),
        )
        if request_id:
            result["request_id"] = request_id
        result["queued"] = False
        result["queue_wait_seconds"] = int(round(slot_acquired_at - queue_started))
        # 1.12.78 — o diário devolve o payload que o site leria em
        # `/v1/vehicles/command/status`, e o anúncio o entrega na hora. Antes,
        # este desfecho ficava só aqui até o cron do site vir buscá-lo.
        announce_command_result_async(
            environment,
            request_id,
            command_journal_finish(request_hash, request_id, result),
        )
        # Preserve uma janela curta para uma ação manual seguinte. Antes, a
        # telemetria de confirmação assumia a conta após três segundos e
        # abrir/fechar ou travar/destravar em sequência aguardava até 31s.
        defer_seconds = MANUAL_SETTLE_SECONDS
        remote_summary = result.get("remote_result_summary")
        remote_summary_text = (
            json.dumps(remote_summary, ensure_ascii=False, separators=(",", ":"))
            if isinstance(remote_summary, dict) and remote_summary
            else "{}"
        )
        remote_summary_text = connector.clean_message(remote_summary_text)[:320]
        LOG.info(
            "Comando remoto %s finalizado no worker para %s; resultado=%s, espera_fila=%ss, latência_conta=%sms, vaga_connector=%sms, precheck_motor=%sms [status_conta=%sms, trava_motor=%sms, leitura_assinatura=%sms], espera_sessao=%sms, login=%sms, handle_command=%sms, pos_dispatch_local=%sms, arme_confirmacao=%sms, arme_assincrono=%s, [preparo_sessao=%sms, dispatch=%sms, verificacao=%sms, progresso=%sms], nao_atribuido=%sms, execução_remota=%sms, total=%sms, tentativas=%s, despertar_real=%s, repetição_segura=%s, estratégia=%s, confirmado_direto=%s, confirmação_pendente=%s, fast_interno=%s, janela_reutilizada=%s, motivo=%s, ack=%s, resultado_remoto=%s, evidencia=%s, sinal=%s, resumo=%s.",
            str(payload.get("command") or "desconhecido")[:40],
            environment,
            str(result.get("final_outcome") or ("confirmed" if result.get("verified_by_gateway") else "confirmation_pending"))[:40],
            int(result.get("queue_wait_seconds") or 0),
            int(latency.get("account_wait_ms") or 0),
            int(latency.get("connector_slot_ms") or 0),
            int(latency.get("engine_precheck_ms") or 0),
            int(latency.get("auth_status_ms") or 0),
            int(latency.get("engine_lock_wait_ms") or 0),
            int(latency.get("subscription_read_ms") or 0),
            int(latency.get("session_wait_ms") or 0),
            int(latency.get("session_login_ms") or 0),
            int(latency.get("handle_command_ms") or 0),
            int(latency.get("post_dispatch_local_ms") or 0),
            int(latency.get("confirmation_arm_ms") or 0),
            bool(result.get("confirmation_arm_queued")),
            int(latency.get("session_prepare_ms") or 0),
            int(latency.get("dispatch_ms") or 0),
            int(latency.get("verification_ms") or 0),
            int(latency.get("progress_ms") or 0),
            int(latency.get("unaccounted_ms") or 0),
            int(latency.get("remote_execute_ms") or 0),
            int(latency.get("total_ms") or 0),
            int(result.get("attempts") or 1),
            bool(result.get("wake_attempted")),
            bool(result.get("safe_retry_performed")),
            str(result.get("safe_retry_strategy") or "none")[:48],
            bool(result.get("verified_by_gateway")),
            bool(result.get("confirmation_pending")),
            bool(result.get("confirmation_armed_by_gateway")),
            bool(result.get("confirmation_window_reused")),
            str(result.get("confirmation_reason") or "none")[:48],
            str(result.get("dispatch_ack") or "unknown")[:48],
            str(result.get("remote_result_status") or "unknown")[:48],
            str(result.get("remote_result_evidence") or "unknown")[:80],
            str(result.get("remote_result_signal") or "unknown")[:32],
            remote_summary_text,
        )
        if bool(result.get("session_recovered")):
            LOG.info("Comando %s exigiu uma nova sessão após cert/sync recusar o token anterior.", request_id[:12])
        if result.get("execution_warning"):
            LOG.warning(
                "Comando %s chegou à nuvem, mas terminou com diagnóstico %s (estado=%s).",
                request_id[:12],
                str(result.get("execution_warning") or "warning")[:80],
                str(result.get("verification_state") or "unknown")[:80],
            )
    except CommandCancelled:
        defer_seconds = 0
        retry_after_seconds = 0
    except connector.ConnectorLoginCooldownError as exc:
        retry_after_seconds = max(30, min(1800, int(exc.retry_after_seconds or 300)))
        command_journal_wait_auth(request_hash, request_id, retry_after_seconds)
        defer_seconds = 1
        LOG.info(
            "Comando %s aguardará %ss pelo desbloqueio temporário de autenticação; nenhuma nova tentativa será feita antes disso.",
            request_id[:12],
            retry_after_seconds,
        )
    except BaseException as exc:  # noqa: BLE001
        if connector.is_transient_cloud_error(exc) or isinstance(exc, connector.ConnectorTemporaryError):
            ORCHESTRATOR.record_cloud_failure(environment, payload.get("account_id") or payload.get("vehicle_id"))
        command_journal_fail(request_hash, request_id, exc)
        defer_seconds = 3
        LOG.warning("Comando remoto em segundo plano falhou (%s): %s", type(exc).__name__, connector.clean_message(str(exc)))
    finally:
        manual_operation_defer(pending_key, defer_seconds)
        if acquired:
            SEMAPHORE.release()
        if account_acquired and account_lock is not None:
            account_lock.release()
        manual_operation_leave(pending_key)
        def wake_confirmation() -> None:
            try:
                if isinstance(result, dict) and bool(result.get("accepted", True)):
                    EVENT_TRANSPORT.ingest_hint(
                        environment,
                        int(payload.get("account_id") or 0),
                        str(payload.get("vehicle_id") or payload.get("vehicle_remote_id") or ""),
                        source="command_result",
                        event_key=f"command:{str(payload.get('command') or 'remote')[:48]}",
                    )
                else:
                    TELEMETRY.wake_event.set()
            except Exception:
                TELEMETRY.wake_event.set()

        # A confirmação do próprio comando pode começar cedo. O settle continua
        # protegendo a conta contra telemetria de fundo; uma nova ação manual
        # preempta esta confirmação no próximo ponto seguro.
        timer = threading.Timer(1.2 if isinstance(result, dict) else float(defer_seconds) + 0.2, wake_confirmation)
        timer.daemon = True
        timer.start()
        with COMMAND_WORKERS_GUARD:
            COMMAND_WORKERS.pop(worker_key, None)
            cancelled = worker_key in COMMAND_CANCEL_REQUESTS
            if cancelled:
                COMMAND_CANCEL_REQUESTS.discard(worker_key)
        if retry_after_seconds > 0 and request_hash and not cancelled:
            schedule_command_retry(environment, dict(payload), request_hash, request_id, retry_after_seconds)

def start_command_job(
    environment: str, payload: dict[str, Any], request_hash: str | None, request_id: str
) -> bool:
    if not request_hash or not request_id:
        return False
    worker_key = command_worker_key(environment, request_id)
    with COMMAND_WORKERS_GUARD:
        if worker_key in COMMAND_CANCEL_REQUESTS:
            return False
        existing = COMMAND_WORKERS.get(worker_key)
        if existing is not None and existing.is_alive():
            return True
        pending_timer = COMMAND_RETRY_TIMERS.pop(worker_key, None)
        if pending_timer is not None and threading.current_thread() is not pending_timer:
            pending_timer.cancel()
        pending_key = manual_operation_enter(environment, payload)
        TELEMETRY.wake_event.set()
        worker = threading.Thread(
            target=run_command_job,
            args=(environment, dict(payload), request_hash, request_id, pending_key),
            name=f"leaphub-command-{request_id[:8]}",
            daemon=True,
        )
        COMMAND_WORKERS[worker_key] = worker
        worker.start()
    return True



def sync_payload_hash(payload: dict[str, Any]) -> str:
    safe = {
        "account_id": int(payload.get("account_id") or 0),
        "vehicle_id": str(payload.get("vehicle_id") or "")[:190],
        "request_origin": str(payload.get("request_origin") or "vehicle_sync")[:80],
        "force_visual_bytes": bool(payload.get("force_visual_bytes")),
        "force_debug_package": bool(payload.get("force_debug_package")),
        "force_package_refresh": bool(payload.get("force_package_refresh")),
    }
    raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sync_request_hash(environment: str, request_id: str) -> str:
    return hashlib.sha256(f"sync|{environment}|{request_id}".encode("utf-8")).hexdigest()


def sync_journal_begin(environment: str, payload: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    request_id = request_identifier(payload)
    if not request_id:
        return None, None
    now = time.time()
    request_hash = sync_request_hash(environment, request_id)
    payload_hash = sync_payload_hash(payload)
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
                cache_command(request_hash, str(row.get("payload_hash") or ""), str(row.get("status") or "queued"), str(row.get("response_json") or ""), float(row.get("created_at") or now), float(row.get("updated_at") or now), float(row.get("expires_at") or now + 600))
        except (OSError, sqlite3.Error) as exc:
            LOG.debug("Consulta persistente do diário de sync adiada: %s", exc)
    if row is not None:
        existing_payload_hash = str(row.get("payload_hash") or "")
        if existing_payload_hash and not hmac.compare_digest(existing_payload_hash, payload_hash):
            raise ValueError("O identificador da sincronização já pertence a outra solicitação.")
        raw = str(row.get("response_json") or "")
        response: dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    response = parsed
            except (ValueError, TypeError, json.JSONDecodeError):
                response = {}
        status = str(row.get("status") or "queued")
        if status in {"completed", "failed"}:
            response.setdefault("ok", status == "completed")
            response["status"] = status
            response["request_id"] = request_id
            response["duplicate"] = True
            return None, response
        if now - float(row.get("updated_at") or 0) < 180:
            return None, {
                "ok": True, "accepted": True, "queued": True, "sync_pending": True,
                "duplicate": True, "status": status, "request_id": request_id,
                "poll_after_seconds": 2,
                "message": "A sincronização já está em andamento para esta conta.",
                "connector_version": connector.CONNECTOR_VERSION,
            }
    response = {
        "ok": True, "accepted": True, "queued": True, "sync_pending": True,
        "status": "queued", "request_id": request_id, "poll_after_seconds": 2,
        "message": "Sincronização recebida. O Gateway continuará em segundo plano.",
        "connector_version": connector.CONNECTOR_VERSION,
    }
    raw = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    cache_command(request_hash, payload_hash, "queued", raw, now, now, now + 600)
    try:
        with command_db(0.5) as db:
            db.execute(
                "INSERT INTO command_requests(request_hash,payload_hash,status,response_json,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(request_hash) DO UPDATE SET payload_hash=excluded.payload_hash,status=excluded.status,response_json=excluded.response_json,updated_at=excluded.updated_at,expires_at=excluded.expires_at",
                (request_hash, payload_hash, "queued", raw, now, now, now + 600),
            )
            db.commit()
    except (OSError, sqlite3.Error) as exc:
        LOG.debug("Persistência inicial do diário de sync adiada: %s", exc)
    return request_hash, None


def sync_journal_update(request_hash: str, payload_hash: str, request_id: str, status: str, response: dict[str, Any]) -> None:
    now = time.time()
    response = dict(response)
    response["status"] = status
    response["request_id"] = request_id
    raw = json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=connector.json_default)
    cache_command(request_hash, payload_hash, status, raw, now, now, now + 600)
    try:
        with command_db(0.5) as db:
            db.execute(
                "UPDATE command_requests SET status=?,response_json=?,updated_at=?,expires_at=? WHERE request_hash=?",
                (status, raw[:200000], now, now + 600, request_hash),
            )
            db.commit()
    except (OSError, sqlite3.Error) as exc:
        LOG.debug("Persistência do estado de sync adiada: %s", exc)


def sync_journal_status(environment: str, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = request_identifier(payload)
    if not request_id:
        raise ValueError("Identificador da sincronização ausente.")
    request_hash = sync_request_hash(environment, request_id)
    row = cached_command(request_hash)
    if row is None:
        try:
            with command_db(0.3) as db:
                persisted = db.execute(
                    "SELECT payload_hash,status,response_json,created_at,updated_at,expires_at FROM command_requests WHERE request_hash=?",
                    (request_hash,),
                ).fetchone()
            row = dict(persisted) if persisted is not None else None
            if row is not None:
                cache_command(request_hash, str(row.get("payload_hash") or ""), str(row.get("status") or "queued"), str(row.get("response_json") or ""), float(row.get("created_at") or time.time()), float(row.get("updated_at") or time.time()), float(row.get("expires_at") or time.time()+600))
        except (OSError, sqlite3.Error) as exc:
            raise connector.ConnectorTemporaryError("O diário de sincronização está ocupado. A consulta será repetida sem iniciar outro sync.") from exc
    if row is None:
        return {"ok": False, "status": "unknown", "request_id": request_id, "message": "O Gateway ainda não localizou esta sincronização."}
    raw = str(row.get("response_json") or "")
    response: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict): response = parsed
        except (ValueError, TypeError, json.JSONDecodeError):
            response = {}
    status = str(row.get("status") or "queued")
    if status in {"queued", "waiting_account", "waiting_slot", "running"} and time.time() - float(row.get("updated_at") or 0) > 150:
        status = "failed"
        response = {"ok": False, "temporary": True, "retry_after_seconds": 3, "message": "O worker de sincronização não concluiu no tempo esperado. Uma nova sincronização pode ser iniciada com segurança."}
        sync_journal_update(request_hash, str(row.get("payload_hash") or ""), request_id, status, response)
    response["status"] = status
    response["request_id"] = request_id
    if status in {"queued", "waiting_account", "waiting_slot", "running"}:
        response.setdefault("ok", True)
        response.setdefault("accepted", True)
        response["sync_pending"] = True
        response.setdefault("poll_after_seconds", 2 if status != "waiting_account" else 4)
    return response


def run_sync_job(environment: str, payload: dict[str, Any], request_hash: str, request_id: str, pending_key: str) -> None:
    payload_hash = sync_payload_hash(payload)
    queue_started = time.monotonic()
    account_lock: AccountOperationLock | None = None
    account_acquired = False
    acquired = False
    worker_key = f"{environment}:{request_id}"
    try:
        sync_journal_update(request_hash, payload_hash, request_id, "waiting_account", {
            "ok": True, "accepted": True, "queued": True, "sync_pending": True,
            "message": "Aguardando somente a operação atual desta conta terminar.",
        })
        account_lock = account_operation_lock(environment, payload)
        account_acquired = account_lock.acquire(timeout=max(30, MANUAL_WAIT_SECONDS))
        if not account_acquired:
            raise connector.ConnectorTemporaryError("A conta permaneceu ocupada por outra operação. A sincronização não iniciou.")
        account_acquired_at = time.monotonic()
        sync_journal_update(request_hash, payload_hash, request_id, "waiting_slot", {
            "ok": True, "accepted": True, "queued": True, "sync_pending": True,
            "message": "Conta liberada. Aguardando uma vaga do Connector.",
        })
        acquired = SEMAPHORE.acquire(timeout=max(30, MANUAL_WAIT_SECONDS), priority=True)
        if not acquired:
            raise connector.ConnectorTemporaryError("O Connector permaneceu ocupado. A sincronização não foi enviada à nuvem.")
        slot_at = time.monotonic()
        sync_journal_update(request_hash, payload_hash, request_id, "running", {
            "ok": True, "accepted": True, "queued": False, "sync_pending": True,
            "message": "Sincronização em execução na conta.",
        })
        execute_started = time.monotonic()
        result = TELEMETRY.execute_account_operation(environment, payload, sync=True, origin="vehicle_sync")
        execute_finished = time.monotonic()
        result = dict(result) if isinstance(result, dict) else {"ok": False, "message": "Resposta inválida da sincronização."}
        result["sync_pending"] = False
        result["latency"] = {
            "account_wait_ms": int(round((account_acquired_at - queue_started) * 1000)),
            "connector_slot_ms": int(round((slot_at - account_acquired_at) * 1000)),
            "remote_execute_ms": int(round((execute_finished - execute_started) * 1000)),
            "total_ms": int(round((execute_finished - queue_started) * 1000)),
        }
        sync_journal_update(request_hash, payload_hash, request_id, "completed", result)
        LOG.info(
            "Sincronização de veículo concluída no worker para %s; conta=%sms vaga=%sms remoto=%sms total=%sms.",
            environment,
            result["latency"]["account_wait_ms"], result["latency"]["connector_slot_ms"],
            result["latency"]["remote_execute_ms"], result["latency"]["total_ms"],
        )
    except BaseException as exc:  # noqa: BLE001
        response = {
            "ok": False,
            "temporary": bool(connector.is_transient_cloud_error(exc) or isinstance(exc, connector.ConnectorTemporaryError)),
            "retry_after_seconds": 3,
            "sync_pending": False,
            "message": connector.clean_message(str(exc)),
            "connector_version": connector.CONNECTOR_VERSION,
        }
        sync_journal_update(request_hash, payload_hash, request_id, "failed", response)
        LOG.warning("Sincronização em segundo plano falhou (%s): %s", type(exc).__name__, connector.clean_message(str(exc)))
    finally:
        if acquired:
            SEMAPHORE.release()
        if account_acquired and account_lock is not None:
            account_lock.release()
        manual_operation_defer(pending_key, 3)
        manual_operation_leave(pending_key)
        TELEMETRY.wake_event.set()
        with SYNC_WORKERS_GUARD:
            SYNC_WORKERS.pop(worker_key, None)


def start_sync_job(environment: str, payload: dict[str, Any], request_hash: str | None, request_id: str) -> bool:
    if not request_hash or not request_id:
        return False
    worker_key = f"{environment}:{request_id}"
    with SYNC_WORKERS_GUARD:
        existing = SYNC_WORKERS.get(worker_key)
        if existing is not None and existing.is_alive():
            return True
        pending_key = manual_operation_enter(environment, payload)
        worker = threading.Thread(
            target=run_sync_job,
            args=(environment, dict(payload), request_hash, request_id, pending_key),
            name=f"leaphub-sync-{request_id[:8]}",
            daemon=True,
        )
        SYNC_WORKERS[worker_key] = worker
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
    last_error: BaseException | None = None
    for attempt, delay in enumerate((0.0, 0.06, 0.18, 0.42), start=1):
        if delay > 0:
            time.sleep(delay)
        try:
            with NONCE_DB_LOCK, sqlite3.connect(NONCE_DB_PATH, timeout=2.5) as db:
                db.execute("PRAGMA busy_timeout = 2500")
                db.execute("PRAGMA journal_mode = WAL")
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
                return
        except PermissionError:
            raise
        except (OSError, sqlite3.Error) as exc:
            last_error = exc
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                break
    if now - NONCE_DB_LAST_WARNING >= 60:
        NONCE_DB_LAST_WARNING = now
        LOG.warning(
            "Proteção persistente de nonce temporariamente ocupada após novas tentativas; proteção imediata em memória permanece ativa: %s",
            last_error,
        )


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


def account_operation_lock(environment: str, payload: dict[str, Any]) -> AccountOperationLock:
    key = account_operation_key(environment, payload)
    now = time.time()
    with ACCOUNT_LOCKS_GUARD:
        if len(ACCOUNT_LOCKS) > 1024:
            stale: list[str] = []
            for item_key, used_at in ACCOUNT_LOCK_LAST_USED.items():
                lock_item = ACCOUNT_LOCKS.get(item_key)
                if used_at < now - 3600 and lock_item is not None and not lock_item.locked():
                    stale.append(item_key)
            for item_key in stale[:256]:
                ACCOUNT_LOCKS.pop(item_key, None)
                ACCOUNT_LOCK_LAST_USED.pop(item_key, None)
        lock = ACCOUNT_LOCKS.get(key)
        if lock is None:
            lock = AccountOperationLock(key)
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


def manual_operation_active(environment: str, payload: dict[str, Any]) -> bool:
    """Retorna somente operações manuais realmente pendentes/em execução.

    A janela de settle pós-comando não entra aqui: ela continua bloqueando
    telemetria de fundo, mas não deve atrasar a confirmação do próprio comando.
    """
    key = account_operation_key(environment, payload)
    with MANUAL_PENDING_GUARD:
        return MANUAL_PENDING.get(key, 0) > 0


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
    manual_active_provider=manual_operation_active,
)


def connector_ready() -> bool:
    return connector.package_version() is not None and any(len(secret) >= 32 for secret in SECRETS.values())


def public_health_payload() -> dict[str, Any]:
    return {
        "ok": connector_ready(),
        "version": VERSION,
        "api_version": API_VERSION,
        "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
    }


def gateway_services_health() -> dict[str, dict[str, Any]]:
    """Expõe apenas o mínimo necessário para a saúde remota do site."""
    try:
        if not MANAGER_STATUS_PATH.is_file():
            return {}
        age = max(0.0, time.time() - MANAGER_STATUS_PATH.stat().st_mtime)
        if age > 90:
            return {}
        raw = MANAGER_STATUS_PATH.read_text(encoding="utf-8")
        if not raw or len(raw) > 262_144:
            return {}
        payload = json.loads(raw)
        services = payload.get("services") if isinstance(payload, dict) else None
        if not isinstance(services, dict):
            return {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}

    result: dict[str, dict[str, Any]] = {}
    aliases = {
        "connector": "connector",
        "ocpp": "ocpp_wallbox",
        "tunnel": "tunnel",
    }
    for public_name, source_name in aliases.items():
        source = services.get(source_name)
        if not isinstance(source, dict):
            continue
        enabled = bool(source.get("enabled"))
        configured = bool(source.get("configured"))
        process_state = str(source.get("state") or "unknown").strip().lower()
        health = source.get("health") if isinstance(source.get("health"), dict) else {}
        health_ok = bool(health.get("ok"))
        if not enabled:
            state = "disabled"
        elif not configured:
            state = "unconfigured"
        elif process_state == "running" and health_ok:
            state = "healthy"
        elif process_state in {"starting", "stopping"} or (process_state == "running" and not health_ok):
            state = "degraded"
        elif process_state in {"stopped", "failed", "crashed"}:
            state = "down"
        else:
            state = "unknown"
        result[public_name] = {
            "enabled": enabled,
            "configured": configured,
            "state": state,
            "restarts": max(0, int(source.get("restarts") or 0)),
            "message": {
                "healthy": "Serviço ativo e saudável.",
                "degraded": "Serviço ativo com diagnóstico instável.",
                "down": "Serviço interrompido.",
                "disabled": "Serviço desativado.",
                "unconfigured": "Serviço não configurado.",
            }.get(state, "Sem diagnóstico recente."),
        }
    return result


def detailed_health_payload(environment: str) -> dict[str, Any]:
    library = connector.package_version()
    configured = [name for name, secret in SECRETS.items() if len(secret) >= 32]
    return {
        "ok": library is not None and environment in configured,
        "service": SERVICE,
        "message": "Conector remoto pronto." if library is not None and environment in configured else "Confira a chave do ambiente e a biblioteca leapmotor-api.",
        "version": VERSION,
        "api_version": API_VERSION,
        "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
        "minimum_client_api_version": MIN_SUPPORTED_CLIENT_API_VERSION,
        "connector_version": connector.CONNECTOR_VERSION,
        "library_version": library,
        "operation_limiter": SEMAPHORE.snapshot(),
        "operation_isolation": {
            "per_account_locking": True,
            "lock_order": "account_then_connector",
            "global_slot_held_while_waiting_account": False,
            "manual_preemption": True,
        },
        "connection_orchestrator": ORCHESTRATOR.snapshot(environment),
        "event_transport": EVENT_TRANSPORT.snapshot(),
        "python_version": sys.version.split()[0],
        "environment": environment,
        "configured_environments": configured,
        "telemetry_storage": TELEMETRY.storage_status(),
        "gateway_services": gateway_services_health(),
        "uptime_seconds": int(time.time() - STARTED_AT),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "LeapHubConnector"
    protocol_version = "HTTP/1.1"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15.0)
        self.trace_id = trace_identifier("")

    def parse_request(self) -> bool:
        parsed = super().parse_request()
        if parsed:
            self.trace_id = trace_identifier(self.headers.get("X-Request-ID"))
        return parsed

    def log_message(self, fmt: str, *args: Any) -> None:
        line = fmt % args
        if self.client_address[0] in {"127.0.0.1", "::1"}:
            if 'GET /health ' in line and line.endswith(' 200 -'):
                LOG.debug("local healthcheck")
                return
            if 'POST /v1/telemetry/subscriptions/boost ' in line and line.endswith(' 200 -'):
                LOG.debug("local telemetry boost")
                return
            if 'POST /v1/vehicles/command/status ' in line and line.endswith(' 200 -'):
                LOG.debug("local command status")
                return
        LOG.info("%s - %s", self.address_string(), line)

    def send_json(self, status: int, payload: dict[str, Any], *, close_connection: bool = False) -> bool:
        response = dict(payload)
        response.setdefault("trace_id", self.trace_id)
        response.setdefault("gateway_version", VERSION)
        response.setdefault("api_version", API_VERSION)
        body = json_bytes(response)
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Request-ID", self.trace_id)
            self.send_header("X-LeapHub-Gateway-Version", VERSION)
            self.send_header("X-LeapHub-API-Version", str(API_VERSION))
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
            self.send_header("Referrer-Policy", "no-referrer")
            retry_after = int(response.get("retry_after_seconds") or 0)
            if retry_after > 0:
                self.send_header("Retry-After", str(min(86400, retry_after)))
            should_close = close_connection or bool(getattr(self, "close_connection", False))
            if should_close:
                self.send_header("Connection", "close")
                self.close_connection = True
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
                self.send_json(403, {"ok": False}, close_connection=True)
                return
            if path == "/health/details":
                details = detailed_health_payload(environment)
                details["telemetry"] = TELEMETRY.status_fast()
                self.send_json(200, details, close_connection=True)
            else:
                self.send_json(200, TELEMETRY.status(), close_connection=True)
            return
        self.send_json(404, {"ok": False, "message": "Página não encontrada."}, close_connection=True)

    def do_POST(self) -> None:
        # As chamadas assinadas vêm do PHP/Cloudflare e não reutilizam o socket.
        # Encerrar explicitamente evita que o handler espere mais 15 segundos por
        # uma segunda requisição que nunca virá e registre um timeout falso.
        self.close_connection = True
        requested_api = client_api_version(self.headers)
        if requested_api < MIN_SUPPORTED_CLIENT_API_VERSION or requested_api > API_VERSION:
            self.send_json(409, {
                "ok": False,
                "incompatible_api": True,
                "message": "Versão de integração incompatível. Atualize o Leap Hub ou o Gateway.",
                "requested_api_version": requested_api,
                "supported_api_version": API_VERSION,
            })
            return
        if self.path not in {"/v1/accounts/test", "/v1/vehicles/sync", "/v1/vehicles/sync/status", "/v1/vehicles/command", "/v1/vehicles/command/status", "/v1/vehicles/command/cancel", "/v1/telemetry/subscriptions/upsert", "/v1/telemetry/subscriptions/remove", "/v1/telemetry/subscriptions/boost", "/v1/telemetry/subscriptions/release", "/v1/vehicles/driving-record"}:
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
            if self.path in {"/v1/telemetry/subscriptions/boost", "/v1/telemetry/subscriptions/release", "/v1/vehicles/command/status", "/v1/vehicles/sync/status"}:
                LOG.debug("Action %s accepted for %s trace=%s", self.path, environment, self.trace_id)
            else:
                LOG.info("Action %s accepted for %s trace=%s", self.path, environment, self.trace_id)
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
            if self.path == "/v1/vehicles/sync/status":
                self.send_json(200, sync_journal_status(environment, payload))
                return
            if self.path == "/v1/vehicles/command/status":
                self.send_json(200, command_journal_status(environment, payload))
                return
            if self.path == "/v1/vehicles/command/cancel":
                cancelled = command_journal_cancel(environment, payload)
                self.send_json(200 if bool(cancelled.get("cancelled")) else 409, cancelled)
                return
            if self.path == "/v1/vehicles/sync":
                sync_id = request_identifier(payload)
                if sync_id:
                    sync_journal_key, sync_replay = sync_journal_begin(environment, payload)
                    if sync_replay is not None:
                        self.send_json(200, sync_replay)
                        return
                    if sync_journal_key is not None and start_sync_job(environment, payload, sync_journal_key, sync_id):
                        self.send_json(200, {
                            "ok": True, "accepted": True, "queued": True, "sync_pending": True,
                            "status": "queued", "request_id": sync_id, "poll_after_seconds": 2,
                            "message": "Sincronização recebida. O worker continuará sem manter o túnel HTTP aberto.",
                            "connector_version": connector.CONNECTOR_VERSION,
                        })
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
            account_lock: AccountOperationLock | None = None
            try:
                acquired = SEMAPHORE.acquire(timeout=MANUAL_WAIT_SECONDS, priority=True)
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
                if self.path == "/v1/vehicles/driving-record":
                    # 1.12.72 - diagnostico read-only do historico da nuvem. Passa
                    # pelas MESMAS travas das demais leituras de conta: ele fala com
                    # a Leapmotor, entao nao pode furar a fila nem competir com um
                    # comando do dono.
                    result = connector.handle_driving_record(payload)
                elif self.path == "/v1/accounts/test":
                    result = TELEMETRY.execute_account_operation(environment, payload, sync=False, origin="account_test")
                elif self.path == "/v1/vehicles/sync":
                    result = TELEMETRY.execute_account_operation(environment, payload, sync=True, origin="vehicle_sync")
                else:
                    # Fallback síncrono para clientes antigos sem request_id.
                    # Clientes atuais entram na fila protegida e recebem resposta imediata.
                    if command_journal_key is None:
                        command_journal_key, replay = command_journal_begin(environment, payload)
                        if replay is not None:
                            self.send_json(200, replay)
                            return
                    try:
                        result = TELEMETRY.execute_command(environment, payload)
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
        except connector.ConnectorLoginCooldownError as exc:
            LOG.info("Autenticação temporariamente limitada; nova tentativa permitida em %ss.", exc.retry_after_seconds)
            self.send_json(503, {
                "ok": False,
                "temporary": True,
                "waiting_auth": True,
                "retry_after_seconds": int(exc.retry_after_seconds),
                "message": connector.clean_message(str(exc)),
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
