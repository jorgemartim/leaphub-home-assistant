#!/usr/bin/env python3
"""Leap Hub OCPP 1.6 JSON gateway.

Pure Python WebSocket server that can run locally behind a reverse proxy or as
an external service behind Cloudflare Tunnel. Business rules and persistence remain in the PHP
application through an HTTPS API signed with HMAC.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
try:
    from leaphub_privacy import install_logging_privacy_filter
except ModuleNotFoundError:
    from privacy import install_logging_privacy_filter
import os
import re
import secrets
import signal
import ssl
import sqlite3
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GATEWAY_VERSION = "1.12.18"
IS_RAILWAY = bool(os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("RAILWAY_SERVICE_ID"))
RUNTIME_DIR = Path(os.getenv("LEAPHUB_RUNTIME_DIR", "/tmp/leaphub-ocpp" if IS_RAILWAY else "."))
BIND = os.getenv("LEAPHUB_OCPP_BIND", "0.0.0.0")
PORT = int(os.getenv("PORT") or os.getenv("LEAPHUB_OCPP_PORT", "8092"))
LEGACY_INTERNAL_URL = os.getenv("LEAPHUB_INTERNAL_URL", "").strip()
BETA_INTERNAL_URL = os.getenv("LEAPHUB_BETA_INTERNAL_URL", LEGACY_INTERNAL_URL or "https://leaphub.com.br/beta/leap/api/internal/ocpp").strip()
PRODUCTION_INTERNAL_URL = os.getenv("LEAPHUB_PRODUCTION_INTERNAL_URL", LEGACY_INTERNAL_URL or "https://leaphub.com.br/leap/api/internal/ocpp").strip()
SECRET_FILE = Path(os.getenv("LEAPHUB_GATEWAY_SECRET_FILE", str(RUNTIME_DIR / "ocpp-gateway-secret.txt")))
STATUS_FILE = Path(os.getenv("LEAPHUB_STATUS_FILE", str(RUNTIME_DIR / "ocpp-gateway-status.json")))
PID_FILE = Path(os.getenv("LEAPHUB_PID_FILE", str(RUNTIME_DIR / "ocpp-gateway.pid")))
LOG_FILE = Path(os.getenv("LEAPHUB_LOG_FILE", str(RUNTIME_DIR / "ocpp-gateway.log")))
SERVICE_NAME = os.getenv("RAILWAY_SERVICE_NAME", os.getenv("LEAPHUB_SERVICE_NAME", "leaphub-ocpp"))
DEPLOYMENT_ID = os.getenv("RAILWAY_DEPLOYMENT_ID", "")
RAILWAY_ENVIRONMENT = os.getenv("RAILWAY_ENVIRONMENT_NAME", "")
PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
ENVIRONMENT_LABEL = os.getenv("LEAPHUB_ENVIRONMENT", "unified")
GATEWAY_MODE = os.getenv("LEAPHUB_GATEWAY_MODE", "home_assistant_tunnel")
GATEWAY_PROVIDER = os.getenv("LEAPHUB_GATEWAY_PROVIDER", "home_assistant_tunnel")
MAX_FRAME_BYTES = int(os.getenv("LEAPHUB_OCPP_MAX_FRAME_BYTES", str(1024 * 1024)))
COMMAND_POLL_SECONDS = float(os.getenv("LEAPHUB_OCPP_COMMAND_POLL", "2.0"))
COMMAND_IDLE_POLL_SECONDS = float(os.getenv("LEAPHUB_OCPP_COMMAND_IDLE_POLL", "10.0"))
STATUS_REPORT_SECONDS = max(15.0, float(os.getenv("LEAPHUB_OCPP_STATUS_INTERVAL", "30")))
MAX_CONNECTIONS = max(1, int(os.getenv("LEAPHUB_OCPP_MAX_CONNECTIONS", "1000")))
MAX_CONNECTIONS_PER_IP = max(1, int(os.getenv("LEAPHUB_OCPP_MAX_CONNECTIONS_PER_IP", "50")))
AUTH_FAILURE_WINDOW_SECONDS = max(60, int(os.getenv("LEAPHUB_OCPP_AUTH_WINDOW", "300")))
AUTH_FAILURE_LIMIT = max(3, int(os.getenv("LEAPHUB_OCPP_AUTH_FAILURE_LIMIT", "20")))
AUTH_BLOCK_SECONDS = max(60, int(os.getenv("LEAPHUB_OCPP_AUTH_BLOCK_SECONDS", "600")))
PING_INTERVAL_SECONDS = max(15.0, float(os.getenv("LEAPHUB_OCPP_PING_INTERVAL", "30")))
LIVENESS_TIMEOUT_SECONDS = max(60.0, float(os.getenv("LEAPHUB_OCPP_LIVENESS_TIMEOUT", "120")))
DISCONNECT_GRACE_SECONDS = max(0.0, min(30.0, float(os.getenv("LEAPHUB_OCPP_DISCONNECT_GRACE", "8"))))
EVENT_QUEUE_MAX = max(100, int(os.getenv("LEAPHUB_OCPP_QUEUE_MAX", "10000")))
EVENT_QUEUE_RETENTION_SECONDS = max(86400, int(os.getenv("LEAPHUB_OCPP_QUEUE_RETENTION_SECONDS", str(7 * 86400))))
STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
DIAGNOSTIC_WINDOW_SECONDS = 180
DIAGNOSTIC_NONCES: dict[str, float] = {}
STATUS_API_LAST_ERROR = ""
STATUS_API_LAST_LOG_AT = 0.0
API_CONNECTIONS: dict[tuple[str, int], dict[str, Any]] = {}
API_CONNECTIONS_GUARD = threading.RLock()
API_SSL_CONTEXT = ssl.create_default_context()


for path in (STATUS_FILE, PID_FILE, LOG_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=os.getenv("LEAPHUB_OCPP_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
install_logging_privacy_filter()
LOG = logging.getLogger("leaphub.ocpp")


def configured_secret(name: str) -> str:
    specific = os.getenv(f"LEAPHUB_{name.upper()}_GATEWAY_SECRET", "").strip()
    legacy = os.getenv("LEAPHUB_GATEWAY_SECRET", "").strip()
    secret = specific or legacy
    if not secret:
        try:
            secret = SECRET_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            secret = ""
    if secret and len(secret) < 32:
        raise RuntimeError(f"Gateway secret for {name} is invalid.")
    return secret


@dataclass(frozen=True)
class ApiTarget:
    name: str
    url: str
    secret: str


def configured_targets() -> list[ApiTarget]:
    """Carrega exatamente um destino OCPP por processo.

    A porta pública continua única. O ambiente proprietário é escolhido pelo
    manager e nunca é descoberto consultando Beta e Produção em paralelo.
    """
    environment = ENVIRONMENT_LABEL if ENVIRONMENT_LABEL in {"staging", "production"} else ""
    if environment:
        name = "beta" if environment == "staging" else "production"
        selected_url = LEGACY_INTERNAL_URL or (BETA_INTERNAL_URL if environment == "staging" else PRODUCTION_INTERNAL_URL)
        secret = configured_secret(name)
        return [ApiTarget(environment, selected_url, secret)] if selected_url and secret else []

    candidates: list[ApiTarget] = []
    for name, url, secret_name in (
        ("staging", BETA_INTERNAL_URL, "beta"),
        ("production", PRODUCTION_INTERNAL_URL, "production"),
    ):
        secret = configured_secret(secret_name)
        if url and secret and all(existing.url != url for existing in candidates):
            candidates.append(ApiTarget(name, url, secret))
    if len(candidates) > 1:
        raise RuntimeError("OCPP ambíguo: defina LEAPHUB_ENVIRONMENT como staging ou production.")
    return candidates


API_TARGETS = configured_targets()
TARGETS_BY_NAME = {target.name: target for target in API_TARGETS}
STATE_DB = Path(os.getenv("LEAPHUB_OCPP_STATE_DB", str(RUNTIME_DIR / "ocpp-state.sqlite")))
STATE_DB_INIT_LOCK = threading.Lock()
STATE_DB_INITIALIZED = False
QUEUE_LAST_REPLAY_AT = 0.0
QUEUE_LAST_REPLAY_ERROR = ""
ROUTE_CACHE_SECONDS = max(3600, int(os.getenv("LEAPHUB_OCPP_ROUTE_CACHE_SECONDS", str(14 * 86400))))
RESILIENT_ACTIONS = {
    "BootNotification",
    "Heartbeat",
    "StatusNotification",
    "MeterValues",
    "FirmwareStatusNotification",
    "DiagnosticsStatusNotification",
}


def state_db() -> sqlite3.Connection:
    global STATE_DB_INITIALIZED
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE_DB, timeout=5.0)
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA foreign_keys=ON")
    if not STATE_DB_INITIALIZED:
        with STATE_DB_INIT_LOCK:
            if not STATE_DB_INITIALIZED:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=NORMAL")
                db.execute("""CREATE TABLE IF NOT EXISTS routes (
                    identity TEXT PRIMARY KEY,
                    target_name TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )""")
                db.execute("""CREATE TABLE IF NOT EXISTS event_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_name TEXT NOT NULL,
                    identity TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    ocpp_action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    last_error TEXT NULL,
                    UNIQUE(target_name, identity, message_id, ocpp_action)
                )""")
                db.execute("""CREATE TABLE IF NOT EXISTS command_result_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_name TEXT NOT NULL,
                    identity TEXT NOT NULL,
                    command_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    error_text TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    last_error TEXT NULL,
                    UNIQUE(target_name, identity, command_id)
                )""")
                db.execute("CREATE INDEX IF NOT EXISTS idx_ocpp_event_due ON event_queue(available_at,id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_ocpp_event_identity ON event_queue(target_name,identity,id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_ocpp_result_due ON command_result_queue(available_at,id)")
                db.commit()
                STATE_DB_INITIALIZED = True
    return db


def prune_queues(db: sqlite3.Connection) -> None:
    cutoff = time.time() - EVENT_QUEUE_RETENTION_SECONDS
    db.execute("DELETE FROM event_queue WHERE created_at < ?", (cutoff,))
    db.execute("DELETE FROM command_result_queue WHERE created_at < ?", (cutoff,))
    total = int(db.execute("SELECT COUNT(*) FROM event_queue").fetchone()[0])
    if total > EVENT_QUEUE_MAX:
        excess = total - EVENT_QUEUE_MAX
        # Heartbeat/MeterValues são reconstruídos naturalmente; descarte-os antes
        # de eventos de transação, boot ou estado quando a fila atingir o limite.
        db.execute(
            "DELETE FROM event_queue WHERE id IN (SELECT id FROM event_queue "
            "ORDER BY CASE WHEN ocpp_action IN ('Heartbeat','MeterValues') THEN 0 ELSE 1 END, id ASC LIMIT ?)",
            (excess,),
        )
    result_total = int(db.execute("SELECT COUNT(*) FROM command_result_queue").fetchone()[0])
    if result_total > EVENT_QUEUE_MAX:
        db.execute(
            "DELETE FROM command_result_queue WHERE id IN "
            "(SELECT id FROM command_result_queue ORDER BY id ASC LIMIT ?)",
            (result_total - EVENT_QUEUE_MAX,),
        )


def has_pending_event(target: ApiTarget, identity: str) -> bool:
    try:
        with state_db() as db:
            return db.execute(
                "SELECT 1 FROM event_queue WHERE target_name=? AND identity=? LIMIT 1",
                (target.name, identity),
            ).fetchone() is not None
    except sqlite3.Error:
        return False


def cached_target(identity: str) -> ApiTarget | None:
    try:
        with state_db() as db:
            row = db.execute("SELECT target_name, updated_at FROM routes WHERE identity=?", (identity,)).fetchone()
        if not row or time.time() - float(row[1]) > ROUTE_CACHE_SECONDS:
            return None
        return TARGETS_BY_NAME.get(str(row[0]))
    except sqlite3.Error as exc:
        LOG.warning("OCPP route cache unavailable: %s", exc)
        return None


def remember_route(identity: str, target_name: str) -> None:
    if target_name not in TARGETS_BY_NAME:
        return
    try:
        with state_db() as db:
            db.execute(
                "INSERT INTO routes(identity,target_name,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(identity) DO UPDATE SET target_name=excluded.target_name, updated_at=excluded.updated_at",
                (identity, target_name, time.time()),
            )
            # Eventos e resultados gerados antes da promoção devem acompanhar
            # a mesma identidade para o novo ambiente. INSERT OR IGNORE evita
            # duplicar uma mensagem que já tenha sido reencaminhada.
            db.execute(
                "INSERT OR IGNORE INTO event_queue(target_name,identity,message_id,ocpp_action,payload_json,attempts,available_at,created_at,last_error) "
                "SELECT ?,identity,message_id,ocpp_action,payload_json,attempts,available_at,created_at,last_error "
                "FROM event_queue WHERE identity=? AND target_name<>?",
                (target_name, identity, target_name),
            )
            db.execute("DELETE FROM event_queue WHERE identity=? AND target_name<>?", (identity, target_name))
            db.execute(
                "INSERT OR IGNORE INTO command_result_queue(target_name,identity,command_id,status,payload_json,error_text,attempts,available_at,created_at,last_error) "
                "SELECT ?,identity,command_id,status,payload_json,error_text,attempts,available_at,created_at,last_error "
                "FROM command_result_queue WHERE identity=? AND target_name<>?",
                (target_name, identity, target_name),
            )
            db.execute("DELETE FROM command_result_queue WHERE identity=? AND target_name<>?", (identity, target_name))
            db.commit()
    except sqlite3.Error as exc:
        LOG.warning("Could not persist OCPP route for %s: %s", identity, exc)


def queue_event(target: ApiTarget, identity: str, message_id: str, action: str, payload: dict[str, Any], error: str) -> None:
    try:
        with state_db() as db:
            if action == "Heartbeat":
                db.execute(
                    "DELETE FROM event_queue WHERE target_name=? AND identity=? AND ocpp_action='Heartbeat'",
                    (target.name, identity),
                )
            db.execute(
                "INSERT OR IGNORE INTO event_queue(target_name,identity,message_id,ocpp_action,payload_json,attempts,available_at,created_at,last_error) "
                "VALUES(?,?,?,?,?,0,?,?,?)",
                (target.name, identity, message_id, action, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), time.time(), time.time(), error[:300]),
            )
            prune_queues(db)
            db.commit()
    except sqlite3.Error as exc:
        LOG.error("Could not queue OCPP event %s for %s: %s", action, identity, exc)


def queue_command_result(target: ApiTarget, identity: str, command_id: int, status: str, payload: dict[str, Any], error: str, last_error: str) -> None:
    try:
        with state_db() as db:
            db.execute(
                "INSERT INTO command_result_queue(target_name,identity,command_id,status,payload_json,error_text,attempts,available_at,created_at,last_error) "
                "VALUES(?,?,?,?,?,?,0,?,?,?) ON CONFLICT(target_name,identity,command_id) DO UPDATE SET "
                "status=excluded.status,payload_json=excluded.payload_json,error_text=excluded.error_text,available_at=excluded.available_at,last_error=excluded.last_error",
                (target.name, identity, command_id, status, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), error[:500], time.time(), time.time(), last_error[:300]),
            )
            prune_queues(db)
            db.commit()
    except sqlite3.Error as exc:
        LOG.error("Could not queue OCPP command result %s for %s: %s", command_id, identity, exc)


def queue_counts() -> tuple[int, int, int]:
    try:
        with state_db() as db:
            pending = int(db.execute("SELECT COUNT(*) FROM event_queue").fetchone()[0])
            command_results = int(db.execute("SELECT COUNT(*) FROM command_result_queue").fetchone()[0])
            routes = int(db.execute("SELECT COUNT(*) FROM routes").fetchone()[0])
        return pending, command_results, routes
    except sqlite3.Error:
        return 0, 0, 0


def queue_diagnostics() -> dict[str, Any]:
    try:
        with state_db() as db:
            now = time.time()
            event = db.execute("SELECT COUNT(*),MIN(created_at),MAX(attempts) FROM event_queue").fetchone()
            result = db.execute("SELECT COUNT(*),MIN(created_at),MAX(attempts) FROM command_result_queue").fetchone()
        return {
            "oldest_event_age_seconds": max(0, int(now - float(event[1]))) if event and event[1] is not None else 0,
            "oldest_result_age_seconds": max(0, int(now - float(result[1]))) if result and result[1] is not None else 0,
            "max_event_attempts": int(event[2] or 0) if event else 0,
            "max_result_attempts": int(result[2] or 0) if result else 0,
            "last_replay_at": QUEUE_LAST_REPLAY_AT,
            "last_replay_error": QUEUE_LAST_REPLAY_ERROR[:200],
        }
    except sqlite3.Error:
        return {}


def local_response(action: str, authorization: dict[str, Any] | None = None) -> dict[str, Any]:
    if action == "BootNotification":
        interval = int((authorization or {}).get("heartbeat_interval", 60) or 60)
        return {"status": "Accepted", "currentTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "interval": max(30, min(3600, interval))}
    if action == "Heartbeat":
        return {"currentTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return {}


def safe_http_error_detail(code: int, raw: bytes) -> str:
    text = raw.decode("utf-8", "replace").strip(); lowered = text.lower()
    if not text or "<!doctype html" in lowered or "<html" in lowered: return f"HTTP {code}"
    try:
        decoded=json.loads(text)
        if isinstance(decoded,dict):
            message=str(decoded.get("message") or decoded.get("error") or "").strip()
            return f"HTTP {code}: {message[:180]}" if message else f"HTTP {code}"
    except json.JSONDecodeError: pass
    return f"HTTP {code}: {re.sub(r'\s+', ' ', text)[:180]}"


def _api_connection_state(target: ApiTarget) -> dict[str, Any]:
    # Uma conexão persistente por worker evita handshakes repetidos sem
    # serializar todas as wallboxes em um único socket.
    key = (target.url, threading.get_ident())
    with API_CONNECTIONS_GUARD:
        state = API_CONNECTIONS.get(key)
        if state is None:
            state = {"connection": None, "lock": threading.RLock()}
            API_CONNECTIONS[key] = state
        return state


def _drop_api_connection(target: ApiTarget) -> None:
    state = _api_connection_state(target)
    with state["lock"]:
        connection = state.get("connection")
        state["connection"] = None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def _new_api_connection(target: ApiTarget, timeout: float) -> tuple[http.client.HTTPConnection, str]:
    parsed = urllib.parse.urlsplit(target.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError(f"Internal API {target.name} has an invalid URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    if parsed.scheme == "https":
        connection: http.client.HTTPConnection = http.client.HTTPSConnection(
            parsed.hostname, port, timeout=timeout, context=API_SSL_CONTEXT
        )
    else:
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
    return connection, path


def api_call(target: ApiTarget, payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    parsed_path = urllib.parse.urlsplit(target.url).path or "/api/internal/ocpp"
    state = _api_connection_state(target)
    last_error: Exception | None = None
    with state["lock"]:
        for attempt in range(2):
            timestamp = str(int(time.time()))
            nonce = secrets.token_hex(16)
            canonical = f"POST\n{parsed_path}\n{timestamp}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode("utf-8")
            signature = hmac.new(target.secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "keep-alive",
                "X-LeapHub-Timestamp": timestamp,
                "X-LeapHub-Nonce": nonce,
                "X-LeapHub-Signature": signature,
                "User-Agent": f"LeapHub-OCPP-Gateway/{GATEWAY_VERSION}",
            }
            connection = state.get("connection")
            path = ""
            try:
                if connection is None:
                    connection, path = _new_api_connection(target, timeout)
                    state["connection"] = connection
                else:
                    path = urllib.parse.urlunsplit(("", "", urllib.parse.urlsplit(target.url).path or "/", urllib.parse.urlsplit(target.url).query, ""))
                    connection.timeout = timeout
                    if connection.sock is not None:
                        connection.sock.settimeout(timeout)
                connection.request("POST", path, body=body, headers=headers)
                response = connection.getresponse()
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise RuntimeError(f"Internal API {target.name} returned a response above the limit")
                if response.will_close or response.getheader("Connection", "").lower() == "close":
                    state["connection"] = None
                    connection.close()
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(
                        f"Internal API {target.name} rejected request: {safe_http_error_detail(response.status, raw[:4096])}"
                    )
                try:
                    decoded = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(f"Internal API {target.name} returned a non-JSON response") from exc
                if not isinstance(decoded, dict) or not decoded.get("ok"):
                    message = str(decoded.get("message", "Internal API returned an invalid response.")) if isinstance(decoded, dict) else "Invalid response"
                    raise RuntimeError(f"Internal API {target.name}: {message[:200]}")
                return decoded
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                last_error = exc
                state["connection"] = None
                try:
                    connection.close()
                except (AttributeError, OSError):
                    pass
                if attempt == 0:
                    continue
                detail = "read operation timed out" if "timed out" in str(exc).lower() else str(exc)
                raise RuntimeError(f"Internal API {target.name} unavailable: {detail}") from exc
    raise RuntimeError(f"Internal API {target.name} unavailable: {last_error or 'unknown transport error'}")


def resolve_route(identity: str, password: str, remote_ip: str) -> tuple[ApiTarget, dict[str, Any]]:
    cached = cached_target(identity)
    if cached is not None:
        try:
            result = api_call(cached, {"action": "authorize_connection", "identity": identity, "password": password, "remote_ip": remote_ip}, 4.0)
        except RuntimeError as exc:
            # Uma rota conhecida indisponível não é falha de senha e não deve
            # fazer a wallbox alternar entre Beta e Produção.
            raise RuntimeError(str(exc)) from exc
        if result.get("accepted"):
            remember_route(identity, cached.name)
            return cached, result
        candidates = [target for target in API_TARGETS if target != cached]
    else:
        candidates = list(API_TARGETS)

    unavailable: list[str] = []
    rejected = 0
    for target in candidates:
        try:
            result = api_call(target, {"action": "authorize_connection", "identity": identity, "password": password, "remote_ip": remote_ip}, 4.0)
        except RuntimeError as exc:
            unavailable.append(str(exc))
            continue
        if result.get("accepted"):
            remember_route(identity, target.name)
            return target, result
        rejected += 1
    if unavailable:
        raise RuntimeError("; ".join(unavailable[:2]))
    if rejected > 0 or cached is not None:
        raise PermissionError("Charge point is not approved")
    raise RuntimeError("No OCPP API target is currently available")


def parse_headers(raw: bytes) -> tuple[str, str, dict[str, str]]:
    text = raw.decode("latin-1")
    lines = text.split("\r\n")
    request_line = lines[0].split(" ")
    if len(request_line) != 3:
        raise ValueError("Invalid HTTP request line")
    method, target, _version = request_line
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return method.upper(), target, headers


def extract_identity(target: str) -> str:
    path = urllib.parse.urlsplit(target).path
    marker = "/ocpp/1.6/"
    position = path.find(marker)
    if position < 0:
        return ""
    identity = urllib.parse.unquote(path[position + len(marker) :]).strip("/")
    if not identity or "/" in identity or len(identity) > 120:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
    return identity if all(ch in allowed for ch in identity) else ""


def basic_credentials(headers: dict[str, str]) -> tuple[str, str]:
    value = headers.get("authorization", "")
    if not value.lower().startswith("basic "):
        return "", ""
    try:
        decoded = base64.b64decode(value.split(" ", 1)[1], validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return "", ""
    if ":" not in decoded:
        return "", ""
    return tuple(decoded.split(":", 1))  # type: ignore[return-value]


async def read_http_request(reader: asyncio.StreamReader) -> bytes:
    data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
    if len(data) > 16384:
        raise ValueError("HTTP headers too large")
    return data


def security_headers(content_type: str, content_length: int) -> bytes:
    return (
        "Connection: close\r\n"
        f"Content-Type: {content_type}\r\n"
        "Cache-Control: no-store, no-cache, must-revalidate, max-age=0\r\n"
        "Pragma: no-cache\r\n"
        "X-Content-Type-Options: nosniff\r\n"
        "X-Robots-Tag: noindex, nofollow, noarchive\r\n"
        "Referrer-Policy: no-referrer\r\n"
        f"Content-Length: {content_length}\r\n\r\n"
    ).encode("latin-1")


async def http_error(writer: asyncio.StreamWriter, status: int, reason: str) -> None:
    body = (reason + "\n").encode("utf-8")
    writer.write(
        f"HTTP/1.1 {status} {reason}\r\n".encode("latin-1")
        + security_headers("text/plain; charset=utf-8", len(body))
        + body
    )
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def http_json(writer: asyncio.StreamWriter, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    reasons = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 429: "Too Many Requests", 503: "Service Unavailable"}
    reason = reasons.get(status, "Error")
    writer.write(
        f"HTTP/1.1 {status} {reason}\r\n".encode("latin-1")
        + security_headers("application/json; charset=utf-8", len(body))
        + body
    )
    await writer.drain()
    writer.close()
    await writer.wait_closed()


def public_health_payload() -> dict[str, Any]:
    return {"ok": True}


def detailed_health_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "Leap Hub OCPP Gateway",
        "version": GATEWAY_VERSION,
        "environment": ENVIRONMENT_LABEL,
        "route_order": [target.name for target in API_TARGETS],
        "gateway_mode": GATEWAY_MODE,
        "provider": GATEWAY_PROVIDER,
        "connections": len(CONNECTIONS),
        "max_connections": MAX_CONNECTIONS,
        "started_at": STARTED_AT,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "queued_events": queue_counts()[0],
        "queued_command_results": queue_counts()[1],
        "cached_routes": queue_counts()[2],
    }


def verify_diagnostic_signature(method: str, path: str, headers: dict[str, str]) -> None:
    timestamp = headers.get("x-leaphub-timestamp", "").strip()
    nonce = headers.get("x-leaphub-nonce", "").strip().lower()
    environment = headers.get("x-leaphub-environment", "").strip().lower()
    signature = headers.get("x-leaphub-signature", "").strip().lower()
    if environment not in {"staging", "production", "unified"}:
        raise PermissionError("Invalid environment")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > DIAGNOSTIC_WINDOW_SECONDS:
        raise PermissionError("Expired signature")
    if re.fullmatch(r"[a-f0-9]{32,128}", nonce) is None:
        raise PermissionError("Invalid nonce")
    if re.fullmatch(r"[a-f0-9]{64}", signature) is None:
        raise PermissionError("Missing signature")
    body_hash = hashlib.sha256(b"").hexdigest()
    canonical = f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}".encode("utf-8")
    if environment == "unified":
        secrets_to_try = [target.secret for target in API_TARGETS]
    else:
        target_name = "staging" if environment == "staging" else "production"
        target = TARGETS_BY_NAME.get(target_name)
        secrets_to_try = [target.secret] if target is not None else []
    if not secrets_to_try or not any(
        hmac.compare_digest(hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest(), signature)
        for secret in dict.fromkeys(secrets_to_try)
    ):
        raise PermissionError("Invalid signature")
    now = time.time()
    expired = [key for key, created_at in DIAGNOSTIC_NONCES.items() if created_at < now - DIAGNOSTIC_WINDOW_SECONDS]
    for key in expired:
        DIAGNOSTIC_NONCES.pop(key, None)
    nonce_key = environment + ":" + nonce
    if nonce_key in DIAGNOSTIC_NONCES:
        raise PermissionError("Repeated request")
    DIAGNOSTIC_NONCES[nonce_key] = now


async def read_frame(reader: asyncio.StreamReader) -> tuple[bool, int, bytes]:
    first = await reader.readexactly(2)
    b1, b2 = first
    fin = bool(b1 & 0x80)
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]
    if length > MAX_FRAME_BYTES:
        raise ValueError("WebSocket frame too large")
    if opcode >= 0x8 and (not fin or length > 125):
        raise ValueError("Invalid control frame")
    if not masked:
        raise ValueError("Client WebSocket frames must be masked")
    mask = await reader.readexactly(4)
    payload = await reader.readexactly(length) if length else b""
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return fin, opcode, payload


async def write_frame(writer: asyncio.StreamWriter, opcode: int, payload: bytes = b"") -> None:
    first = 0x80 | (opcode & 0x0F)
    length = len(payload)
    if length < 126:
        header = bytes([first, length])
    elif length <= 0xFFFF:
        header = bytes([first, 126]) + struct.pack("!H", length)
    else:
        header = bytes([first, 127]) + struct.pack("!Q", length)
    writer.write(header + payload)
    await writer.drain()


@dataclass
class ChargePointConnection:
    identity: str
    target: ApiTarget
    authorization: dict[str, Any]
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    remote_ip: str
    writer_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_calls: dict[str, asyncio.Future[list[Any]]] = field(default_factory=dict)
    closed: bool = False
    connection_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    connected_at: float = field(default_factory=time.monotonic)
    last_rx_at: float = field(default_factory=time.monotonic)
    last_pong_at: float = field(default_factory=time.monotonic)
    last_ping_at: float = 0.0

    async def send_json(self, value: list[Any]) -> None:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        async with self.writer_lock:
            await write_frame(self.writer, 0x1, raw)

    async def send_call(self, action: str, payload: dict[str, Any], timeout: float = 35.0) -> list[Any]:
        if self.closed or self.writer.is_closing():
            raise ConnectionError("O carregador desconectou antes do envio do comando.")
        message_id = uuid.uuid4().hex
        future: asyncio.Future[list[Any]] = asyncio.get_running_loop().create_future()
        self.pending_calls[message_id] = future
        await self.send_json([2, message_id, action, payload])
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.pending_calls.pop(message_id, None)

    async def handle_text(self, payload: bytes) -> None:
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            LOG.warning("%s sent invalid JSON", self.identity)
            return
        if not isinstance(message, list) or len(message) < 3:
            LOG.warning("%s sent invalid OCPP envelope", self.identity)
            return
        message_type = message[0]
        if message_type == 2 and len(message) == 4:
            await self.handle_call(str(message[1]), str(message[2]), message[3] if isinstance(message[3], dict) else {})
        elif message_type in (3, 4):
            message_id = str(message[1])
            future = self.pending_calls.get(message_id)
            if future and not future.done():
                future.set_result(message)

    async def handle_call(self, message_id: str, action: str, payload: dict[str, Any]) -> None:
        request_payload = {
            "action": "ocpp_call",
            "identity": self.identity,
            "message_id": message_id,
            "ocpp_action": action,
            "payload": payload,
        }
        if action in RESILIENT_ACTIONS and await asyncio.to_thread(has_pending_event, self.target, self.identity):
            queue_event(self.target, self.identity, message_id, action, payload, "Aguardando eventos anteriores da mesma wallbox.")
            await self.send_json([3, message_id, local_response(action, self.authorization)])
            LOG.info("Queued %s from %s to preserve event order.", action, self.identity)
            return
        try:
            result = await asyncio.to_thread(api_call, self.target, request_payload, 5.0)
        except Exception as exc:  # noqa: BLE001
            if action in RESILIENT_ACTIONS:
                queue_event(self.target, self.identity, message_id, action, payload, str(exc))
                await self.send_json([3, message_id, local_response(action, self.authorization)])
                LOG.warning("Queued %s from %s after API failure: %s", action, self.identity, exc)
                return
            LOG.warning("Synchronous OCPP action %s from %s failed: %s", action, self.identity, exc)
            await self.send_json([4, message_id, "InternalError", "Request could not be processed.", {}])
            return
        if isinstance(result.get("call_error"), dict):
            error = result["call_error"]
            await self.send_json([4, message_id, str(error.get("code", "InternalError")), str(error.get("description", "Request failed.")), error.get("details") if isinstance(error.get("details"), dict) else {}])
        else:
            response_payload = result.get("response_payload")
            await self.send_json([3, message_id, response_payload if isinstance(response_payload, dict) else {}])

    async def command_loop(self) -> None:
        identity_jitter = (int(hashlib.sha256(self.identity.encode("utf-8")).hexdigest()[:8], 16) % 1500) / 1000.0
        delay = COMMAND_POLL_SECONDS + identity_jitter
        while not self.closed:
            await asyncio.sleep(delay)
            try:
                result = await asyncio.to_thread(api_call, self.target, {"action": "fetch_commands", "identity": self.identity}, 6.0)
                commands = result.get("commands")
                if not isinstance(commands, list): delay = COMMAND_IDLE_POLL_SECONDS; continue
                if commands:
                    delay = COMMAND_POLL_SECONDS + identity_jitter
                    for command in commands:
                        if isinstance(command, dict): await self.execute_command(command)
                else: delay = min(COMMAND_IDLE_POLL_SECONDS + identity_jitter, max(COMMAND_POLL_SECONDS + identity_jitter, delay * 1.6))
            except asyncio.CancelledError: raise
            except Exception as exc:
                delay = min(60.0, max(COMMAND_IDLE_POLL_SECONDS, delay * 2.0))
                LOG.warning("Command polling failed for %s (%s): %s", self.identity, self.target.name, exc)

    async def execute_command(self, command: dict[str, Any]) -> None:
        command_id = int(command.get("id", 0))
        key = str(command.get("command_key", ""))
        parameters = command.get("parameters") if isinstance(command.get("parameters"), dict) else {}
        mapping = command_to_ocpp(key, parameters)
        if mapping is None:
            await self.report_command(command_id, "failed", {}, "Unsupported command mapping.")
            return
        action, payload = mapping
        try:
            response = await self.send_call(action, payload)
            if response[0] == 3:
                result_payload = response[2] if len(response) > 2 and isinstance(response[2], dict) else {}
                await self.report_command(command_id, "completed", result_payload, "")
            else:
                code = str(response[2]) if len(response) > 2 else "CallError"
                description = str(response[3]) if len(response) > 3 else "Command rejected."
                await self.report_command(command_id, "failed", {}, f"{code}: {description}")
        except asyncio.TimeoutError:
            await self.report_command(command_id, "timeout", {}, "The charger did not answer in time.")
        except Exception as exc:  # noqa: BLE001
            await self.report_command(command_id, "failed", {}, str(exc)[:300])

    async def report_command(self, command_id: int, status: str, payload: dict[str, Any], error: str) -> None:
        try:
            await asyncio.to_thread(
                api_call,
                self.target,
                {
                    "action": "command_result",
                    "identity": self.identity,
                    "command_id": command_id,
                    "status": status,
                    "payload": payload,
                    "error": error,
                },
            )
        except Exception as exc:  # noqa: BLE001
            queue_command_result(self.target, self.identity, command_id, status, payload, error, str(exc))
            LOG.error("Could not report command %s result; queued for replay: %s", command_id, exc)

    async def ping_loop(self) -> None:
        while not self.closed:
            await asyncio.sleep(PING_INTERVAL_SECONDS)
            now = time.monotonic()
            if now - self.last_rx_at >= LIVENESS_TIMEOUT_SECONDS:
                raise ConnectionError("O carregador não respondeu aos testes de conexão.")
            self.last_ping_at = now
            async with self.writer_lock:
                await write_frame(self.writer, 0x9, os.urandom(4))

    async def run(self) -> None:
        command_task = asyncio.create_task(self.command_loop())
        ping_task = asyncio.create_task(self.ping_loop())
        fragmented_opcode: int | None = None
        fragmented = bytearray()
        try:
            while True:
                if ping_task.done():
                    error = ping_task.exception()
                    if error is not None:
                        raise error
                try:
                    fin, opcode, payload = await asyncio.wait_for(
                        read_frame(self.reader), timeout=PING_INTERVAL_SECONDS + 15.0
                    )
                except asyncio.TimeoutError:
                    if time.monotonic() - self.last_rx_at >= LIVENESS_TIMEOUT_SECONDS:
                        raise ConnectionError("Conexão OCPP sem tráfego por tempo excessivo.")
                    continue
                self.last_rx_at = time.monotonic()
                if opcode == 0x8:
                    async with self.writer_lock:
                        await write_frame(self.writer, 0x8, payload[:125])
                    break
                if opcode == 0x9:
                    async with self.writer_lock:
                        await write_frame(self.writer, 0xA, payload[:125])
                    continue
                if opcode == 0xA:
                    self.last_pong_at = time.monotonic()
                    continue
                if opcode in (0x1, 0x2):
                    if fin:
                        if opcode == 0x1:
                            await self.handle_text(payload)
                    else:
                        fragmented_opcode = opcode
                        fragmented = bytearray(payload)
                    continue
                if opcode == 0x0 and fragmented_opcode is not None:
                    fragmented.extend(payload)
                    if len(fragmented) > MAX_FRAME_BYTES:
                        raise ValueError("Fragmented message too large")
                    if fin:
                        if fragmented_opcode == 0x1:
                            await self.handle_text(bytes(fragmented))
                        fragmented_opcode = None
                        fragmented.clear()
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self.closed = True
            disconnect_error = ConnectionError("A conexão com o carregador foi encerrada.")
            for future in list(self.pending_calls.values()):
                if not future.done():
                    future.set_exception(disconnect_error)
            self.pending_calls.clear()
            command_task.cancel()
            ping_task.cancel()
            for task in (command_task, ping_task):
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass


def command_to_ocpp(key: str, parameters: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    if key == "remote_start":
        return "RemoteStartTransaction", {
            "connectorId": int(parameters.get("connectorId", 1)),
            "idTag": str(parameters.get("idTag", "LEAPHUB")),
        }
    if key == "remote_stop":
        return "RemoteStopTransaction", {"transactionId": int(parameters.get("transactionId", 0))}
    if key == "unlock_connector":
        return "UnlockConnector", {"connectorId": int(parameters.get("connectorId", 1))}
    if key in ("reset_soft", "reset_hard"):
        return "Reset", {"type": "Hard" if key == "reset_hard" else "Soft"}
    if key in ("availability_operative", "availability_inoperative"):
        return "ChangeAvailability", {
            "connectorId": int(parameters.get("connectorId", 0)),
            "type": "Inoperative" if key == "availability_inoperative" else "Operative",
        }
    if key == "trigger_status":
        payload: dict[str, Any] = {"requestedMessage": "StatusNotification"}
        if int(parameters.get("connectorId", 0)) > 0:
            payload["connectorId"] = int(parameters["connectorId"])
        return "TriggerMessage", payload
    if key == "get_configuration":
        keys = parameters.get("key")
        return "GetConfiguration", {"key": keys} if isinstance(keys, list) and keys else {}
    if key == "change_configuration":
        return "ChangeConfiguration", {
            "key": str(parameters.get("key", "")),
            "value": str(parameters.get("value", "")),
        }
    if key == "set_charging_profile":
        return "SetChargingProfile", {
            "connectorId": int(parameters.get("connectorId", 0)),
            "csChargingProfiles": parameters.get("csChargingProfiles", {}),
        }
    if key == "clear_charging_profile":
        return "ClearChargingProfile", {
            "connectorId": int(parameters.get("connectorId", 0)),
            "chargingProfilePurpose": str(parameters.get("chargingProfilePurpose", "TxDefaultProfile")),
            "stackLevel": int(parameters.get("stackLevel", 0)),
        }
    if key == "send_local_list":
        return "SendLocalList", {
            "listVersion": int(parameters.get("listVersion", 1)),
            "updateType": str(parameters.get("updateType", "Full")),
            "localAuthorizationList": parameters.get("localAuthorizationList", []),
        }
    return None


CONNECTIONS: dict[str, ChargePointConnection] = {}
ACTIVE_BY_IP: dict[str, int] = {}
AUTH_FAILURES: dict[str, list[float]] = {}
AUTH_BLOCKED_UNTIL: dict[str, float] = {}
STOP_EVENT = asyncio.Event()


def normalize_remote_ip(headers: dict[str, str], peer_ip: str) -> str:
    """Aceita cabeçalhos de proxy somente de um peer local/privado confiável."""
    try:
        peer = ipaddress.ip_address(str(peer_ip).strip())
    except ValueError:
        peer = None
    candidates: list[str] = []
    if peer is not None and (peer.is_loopback or peer.is_private):
        candidates.extend([
            headers.get("cf-connecting-ip", ""),
            headers.get("x-real-ip", ""),
            headers.get("x-forwarded-for", "").split(",", 1)[0].strip(),
        ])
    candidates.append(peer_ip)
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return "unknown"


def prune_auth_state(now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    cutoff = current - AUTH_FAILURE_WINDOW_SECONDS
    for remote_ip, attempts in list(AUTH_FAILURES.items()):
        recent = [attempt for attempt in attempts if attempt >= cutoff]
        if recent:
            AUTH_FAILURES[remote_ip] = recent
        else:
            AUTH_FAILURES.pop(remote_ip, None)
    for remote_ip, blocked_until in list(AUTH_BLOCKED_UNTIL.items()):
        if blocked_until <= current:
            AUTH_BLOCKED_UNTIL.pop(remote_ip, None)


def ip_is_blocked(remote_ip: str) -> bool:
    now = time.monotonic()
    prune_auth_state(now)
    return AUTH_BLOCKED_UNTIL.get(remote_ip, 0.0) > now


def record_auth_failure(remote_ip: str) -> None:
    now = time.monotonic()
    prune_auth_state(now)
    attempts = AUTH_FAILURES.setdefault(remote_ip, [])
    attempts.append(now)
    if len(attempts) >= AUTH_FAILURE_LIMIT:
        AUTH_BLOCKED_UNTIL[remote_ip] = now + AUTH_BLOCK_SECONDS
        AUTH_FAILURES.pop(remote_ip, None)
        LOG.warning("Temporarily blocked OCPP authentication attempts from %s", remote_ip)


def clear_auth_failures(remote_ip: str) -> None:
    AUTH_FAILURES.pop(remote_ip, None)
    AUTH_BLOCKED_UNTIL.pop(remote_ip, None)


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    peer_ip = str(peer[0]) if isinstance(peer, tuple) and peer else "unknown"
    remote_ip = peer_ip
    identity = ""
    connection: ChargePointConnection | None = None
    try:
        request_raw = await read_http_request(reader)
        method, target, headers = parse_headers(request_raw)
        remote_ip = normalize_remote_ip(headers, peer_ip)
        if ip_is_blocked(remote_ip):
            await http_error(writer, 429, "Too Many Requests")
            return
        if method != "GET":
            await http_error(writer, 405, "Method Not Allowed")
            return
        request_path = urllib.parse.urlsplit(target).path.rstrip("/") or "/"
        if request_path in ("/health", "/ready"):
            await http_json(writer, 200, public_health_payload())
            return
        if request_path == "/health/details":
            try:
                verify_diagnostic_signature(method, request_path, headers)
            except PermissionError:
                LOG.warning("Private gateway diagnostics rejected from %s", remote_ip)
                await http_json(writer, 403, {"ok": False})
                return
            await http_json(writer, 200, detailed_health_payload())
            return
        if request_path == "/":
            await http_error(writer, 404, "Not Found")
            return
        identity = extract_identity(target)
        if not identity:
            await http_error(writer, 404, "Not Found")
            return
        if headers.get("upgrade", "").lower() != "websocket" or "upgrade" not in headers.get("connection", "").lower():
            await http_error(writer, 426, "Upgrade Required")
            return
        if headers.get("sec-websocket-version") != "13":
            await http_error(writer, 426, "Upgrade Required")
            return
        protocols = [item.strip() for item in headers.get("sec-websocket-protocol", "").split(",") if item.strip()]
        if "ocpp1.6" not in protocols:
            await http_error(writer, 400, "OCPP 1.6 subprotocol required")
            return
        key = headers.get("sec-websocket-key", "")
        try:
            decoded_key = base64.b64decode(key, validate=True)
        except (ValueError, TypeError):
            decoded_key = b""
        if len(decoded_key) != 16:
            await http_error(writer, 400, "Bad Request")
            return
        existing_connection = CONNECTIONS.get(identity)
        replacing_existing = existing_connection is not None and not existing_connection.closed
        effective_connections = len(CONNECTIONS) - (1 if replacing_existing else 0)
        effective_ip_connections = ACTIVE_BY_IP.get(remote_ip, 0)
        if replacing_existing and existing_connection.remote_ip == remote_ip:
            effective_ip_connections = max(0, effective_ip_connections - 1)
        if effective_connections >= MAX_CONNECTIONS:
            await http_error(writer, 503, "Service Unavailable")
            return
        if effective_ip_connections >= MAX_CONNECTIONS_PER_IP:
            await http_error(writer, 429, "Too Many Requests")
            return

        username, password = basic_credentials(headers)
        if username and username != identity:
            record_auth_failure(remote_ip)
            await http_error(writer, 401, "Unauthorized")
            return
        try:
            route_target, authorization = await asyncio.to_thread(resolve_route, identity, password, remote_ip)
        except PermissionError:
            record_auth_failure(remote_ip); await http_error(writer, 401, "Unauthorized"); return
        except RuntimeError as exc:
            LOG.warning("OCPP route resolution unavailable for %s: %s", identity, exc); await http_error(writer, 503, "Service Unavailable"); return
        clear_auth_failures(remote_ip)

        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        writer.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "Sec-WebSocket-Protocol: ocpp1.6\r\n"
                "Server: LeapHub-OCPP\r\n\r\n"
            ).encode("latin-1")
        )
        await writer.drain()
        previous = CONNECTIONS.get(identity)
        if previous and not previous.closed:
            previous.closed = True
            previous.writer.close()
        connection = ChargePointConnection(identity, route_target, authorization, reader, writer, remote_ip)
        CONNECTIONS[identity] = connection
        ACTIVE_BY_IP[remote_ip] = ACTIVE_BY_IP.get(remote_ip, 0) + 1
        LOG.info("Charge point connected: %s route=%s", identity, route_target.name)
        await connection.run()
    except Exception as exc:  # noqa: BLE001
        LOG.warning("Connection failed for %s: %s", identity or peer_ip, exc)
        if not writer.is_closing():
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
    finally:
        is_current_connection = (
            connection is not None
            and identity != ""
            and CONNECTIONS.get(identity) is connection
        )
        if connection is not None:
            current_count = ACTIVE_BY_IP.get(remote_ip, 0) - 1
            if current_count > 0:
                ACTIVE_BY_IP[remote_ip] = current_count
            else:
                ACTIVE_BY_IP.pop(remote_ip, None)
        if is_current_connection:
            CONNECTIONS.pop(identity, None)
            disconnected_at = time.time()
            if DISCONNECT_GRACE_SECONDS > 0:
                await asyncio.sleep(DISCONNECT_GRACE_SECONDS)
            replacement = CONNECTIONS.get(identity)
            if replacement is not None and not replacement.closed:
                LOG.info("Charge point %s reconnected inside the grace window; offline transition suppressed.", identity)
            else:
                try:
                    await asyncio.to_thread(api_call, connection.target, {
                        "action": "disconnect",
                        "identity": identity,
                        "connection_id": connection.connection_id,
                        "connected_for_seconds": max(0, int(time.monotonic() - connection.connected_at)),
                        "disconnected_at_epoch": disconnected_at,
                    }, 5.0)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("Could not record disconnect for %s: %s", identity, exc)
                LOG.info("Charge point disconnected: %s", identity)


def replay_command_results_once(limit: int = 25) -> int:
    now = time.time()
    try:
        with state_db() as db:
            prune_queues(db)
            db.commit()
            rows = db.execute(
                "SELECT id,target_name,identity,command_id,status,payload_json,error_text,attempts FROM command_result_queue WHERE available_at<=? ORDER BY id LIMIT ?",
                (now, limit),
            ).fetchall()
    except sqlite3.Error as exc:
        LOG.warning("OCPP command-result queue read failed: %s", exc)
        return 0
    delivered = 0
    for row in rows:
        result_id, target_name, identity, command_id, status, payload_json, error_text, attempts = row
        target = TARGETS_BY_NAME.get(str(target_name))
        if target is None:
            continue
        try:
            payload = json.loads(str(payload_json))
            api_call(target, {"action": "command_result", "identity": identity, "command_id": int(command_id), "status": status, "payload": payload, "error": str(error_text)}, 6.0)
            with state_db() as db:
                db.execute("DELETE FROM command_result_queue WHERE id=?", (result_id,)); db.commit()
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            attempt_count = int(attempts) + 1
            delay = min(900.0, 5.0 * (2 ** min(attempt_count, 7)))
            with state_db() as db:
                db.execute("UPDATE command_result_queue SET attempts=?,available_at=?,last_error=? WHERE id=?", (attempt_count, time.time()+delay, str(exc)[:300], result_id)); db.commit()
    return delivered


def replay_queue_once(limit: int = 25) -> int:
    global QUEUE_LAST_REPLAY_AT, QUEUE_LAST_REPLAY_ERROR
    now = time.time()
    try:
        with state_db() as db:
            rows = db.execute(
                "SELECT id,target_name,identity,message_id,ocpp_action,payload_json,attempts FROM event_queue WHERE available_at<=? ORDER BY id LIMIT ?",
                (now, limit),
            ).fetchall()
    except sqlite3.Error as exc:
        LOG.warning("OCPP queue read failed: %s", exc)
        return 0
    delivered = 0
    for row in rows:
        event_id, target_name, identity, message_id, action, payload_json, attempts = row
        target = TARGETS_BY_NAME.get(str(target_name))
        if target is None:
            continue
        try:
            payload = json.loads(str(payload_json))
            api_call(target, {"action": "ocpp_call", "identity": identity, "message_id": message_id, "ocpp_action": action, "payload": payload, "gateway_replay": True}, 6.0)
            with state_db() as db:
                db.execute("DELETE FROM event_queue WHERE id=?", (event_id,))
                prune_queues(db)
                db.commit()
            QUEUE_LAST_REPLAY_AT = time.time()
            QUEUE_LAST_REPLAY_ERROR = ""
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            attempt_count = int(attempts) + 1
            delay = min(900.0, 5.0 * (2 ** min(attempt_count, 7)))
            with state_db() as db:
                db.execute("UPDATE event_queue SET attempts=?,available_at=?,last_error=? WHERE id=?", (attempt_count, time.time()+delay, str(exc)[:300], event_id))
                prune_queues(db)
                db.commit()
            QUEUE_LAST_REPLAY_ERROR = str(exc)[:300]
    return delivered


async def queue_loop() -> None:
    while not STOP_EVENT.is_set():
        try:
            delivered_events = await asyncio.to_thread(replay_queue_once, 25)
            delivered_results = await asyncio.to_thread(replay_command_results_once, 25)
            wait = 2.0 if delivered_events or delivered_results else 10.0
        except Exception as exc:  # noqa: BLE001
            LOG.warning("OCPP queue loop failed: %s", exc)
            wait = 30.0
        try:
            await asyncio.wait_for(STOP_EVENT.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass


def apply_route_overrides(source: ApiTarget, result: dict[str, Any]) -> None:
    if source.name != "production":
        return
    overrides = result.get("route_overrides")
    if not isinstance(overrides, list):
        return
    for raw in overrides[:10000]:
        identity = str(raw).strip()
        if not identity:
            continue
        remember_route(identity, "production")
        active = CONNECTIONS.get(identity)
        if active is not None and active.target.name != "production" and not active.closed:
            LOG.info("Promoted OCPP route detected for %s; reconnecting on production", identity)
            active.closed = True
            active.writer.close()


async def status_loop() -> None:
    next_attempt = {target.name: 0.0 for target in API_TARGETS}
    failures = {target.name: 0 for target in API_TARGETS}
    last_errors: dict[str, str] = {}
    last_logged: dict[str, float] = {}
    while not STOP_EVENT.is_set():
        pending_events, pending_command_results, cached_routes = queue_counts()
        queue_status = queue_diagnostics()
        now_mono = time.monotonic()
        status = {
            "pid": os.getpid(), "connections": len(CONNECTIONS),
            "connections_by_route": {target.name: sum(1 for connection in CONNECTIONS.values() if connection.target.name == target.name) for target in API_TARGETS},
            "active_ips": len(ACTIVE_BY_IP), "blocked_ips": len(AUTH_BLOCKED_UNTIL), "auth_failure_ips": len(AUTH_FAILURES),
            "max_connections": MAX_CONNECTIONS, "port": PORT, "started_at": STARTED_AT, "gateway_mode": GATEWAY_MODE,
            "provider": GATEWAY_PROVIDER, "service_name": SERVICE_NAME, "deployment_id": DEPLOYMENT_ID,
            "railway_environment": RAILWAY_ENVIRONMENT, "public_domain": PUBLIC_DOMAIN, "version": GATEWAY_VERSION,
            "unified_endpoint": True, "active_environment": ENVIRONMENT_LABEL, "target_count": len(API_TARGETS),
            "queued_events": pending_events, "queued_command_results": pending_command_results, "cached_routes": cached_routes,
            "connection_liveness": {
                "oldest_rx_age_seconds": max([int(now_mono - c.last_rx_at) for c in CONNECTIONS.values()] or [0]),
                "pending_calls": sum(len(c.pending_calls) for c in CONNECTIONS.values()),
                "ping_interval_seconds": int(PING_INTERVAL_SECONDS),
                "liveness_timeout_seconds": int(LIVENESS_TIMEOUT_SECONDS),
            },
            "queue_diagnostics": queue_status,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        temporary = STATUS_FILE.with_suffix(STATUS_FILE.suffix + ".tmp")
        temporary.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
        temporary.replace(STATUS_FILE)
        now = time.monotonic()
        for target in API_TARGETS:
            if now < next_attempt.get(target.name, 0.0):
                continue
            try:
                result = await asyncio.to_thread(api_call, target, {"action": "gateway_status", **status}, 4.0)
                apply_route_overrides(target, result)
                failures[target.name] = 0; next_attempt[target.name] = now + STATUS_REPORT_SECONDS; last_errors.pop(target.name, None)
            except Exception as exc:  # noqa: BLE001
                failures[target.name] = failures.get(target.name, 0) + 1
                delay = min(900.0, 60.0 * (2 ** min(failures[target.name] - 1, 4)))
                next_attempt[target.name] = now + delay; message = str(exc)
                if message != last_errors.get(target.name) or now - last_logged.get(target.name, 0.0) >= 900:
                    LOG.warning("Gateway status API %s failed; retry in %.0fs: %s", target.name, delay, message)
                    last_errors[target.name] = message; last_logged[target.name] = now
        try:
            await asyncio.wait_for(STOP_EVENT.wait(), timeout=STATUS_REPORT_SECONDS)
        except asyncio.TimeoutError:
            pass


async def main() -> None:
    if not API_TARGETS: raise RuntimeError("At least one internal OCPP API target is required.")
    if GATEWAY_MODE != "local" and any(not target.url.lower().startswith("https://") for target in API_TARGETS): raise RuntimeError("Internal OCPP API targets must use https:// outside local mode.")
    with state_db() as _db:
        pass
    PID_FILE.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    try:
        os.chmod(PID_FILE, 0o600)
    except OSError:
        pass
    server = await asyncio.start_server(handle_client, BIND, PORT, limit=MAX_FRAME_BYTES + 65536)
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    LOG.info("Leap Hub OCPP gateway listening on %s", sockets)
    status_task = asyncio.create_task(status_loop())
    queue_task = asyncio.create_task(queue_loop())
    async with server:
        await STOP_EVENT.wait()
    status_task.cancel()
    queue_task.cancel()
    for task in (status_task, queue_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
    for connection in list(CONNECTIONS.values()):
        connection.closed = True
        connection.writer.close()
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def stop() -> None:
    STOP_EVENT.set()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop)
            except NotImplementedError:
                pass
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
