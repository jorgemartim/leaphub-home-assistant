#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
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

VERSION = "1.11.61"
SERVICE = "Leap Hub Leapmotor Connector"
MAX_BODY = 1024 * 1024
WINDOW_SECONDS = 180
STARTED_AT = time.time()
NONCES: dict[str, float] = {}
NONCE_LOCK = threading.Lock()
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
MAX_PARALLEL = max(1, min(8, int(OPTIONS.get("max_parallel_requests") or 2)))
SEMAPHORE = threading.BoundedSemaphore(MAX_PARALLEL)
MANUAL_WAIT_SECONDS = max(2, min(60, int(OPTIONS.get("manual_wait_seconds") or 20)))
LOG_LEVEL = str(OPTIONS.get("log_level") or "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("leaphub.connector")
TELEMETRY = TelemetryEngine(OPTIONS, SECRETS, SEMAPHORE)


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=connector.json_default).encode("utf-8")


def cleanup_nonces(now: float) -> None:
    expired = [key for key, created in NONCES.items() if created < now - WINDOW_SECONDS]
    for key in expired:
        NONCES.pop(key, None)


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
    nonce_key = environment + ":" + nonce
    now = time.time()
    with NONCE_LOCK:
        cleanup_nonces(now)
        if nonce_key in NONCES:
            raise PermissionError("Requisição repetida.")
        NONCES[nonce_key] = now
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}".encode("utf-8")
    expected = hmac.new(SECRETS[environment].encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        with NONCE_LOCK:
            NONCES.pop(nonce_key, None)
        raise PermissionError("Assinatura inválida.")
    return environment


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
        "uptime_seconds": int(time.time() - STARTED_AT),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "LeapHubConnector"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        line = fmt % args
        if self.client_address[0] in {"127.0.0.1", "::1"} and 'GET /health ' in line and line.endswith(' 200 -'):
            LOG.debug("local healthcheck")
            return
        LOG.info("%s - %s", self.address_string(), line)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
                details["telemetry"] = TELEMETRY.status()
                self.send_json(200, details)
            else:
                self.send_json(200, TELEMETRY.status())
            return
        self.send_json(404, {"ok": False, "message": "Página não encontrada."})

    def do_POST(self) -> None:
        if self.path not in {"/v1/accounts/test", "/v1/vehicles/sync", "/v1/vehicles/command", "/v1/telemetry/subscriptions/upsert", "/v1/telemetry/subscriptions/remove", "/v1/telemetry/subscriptions/boost"}:
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

        try:
            LOG.info("Action %s accepted for %s", self.path, environment)
            if self.path == "/v1/telemetry/subscriptions/upsert":
                self.send_json(200, TELEMETRY.upsert(environment, payload))
                return
            if self.path == "/v1/telemetry/subscriptions/remove":
                self.send_json(200, TELEMETRY.remove(str(payload.get("subscription_id") or "")))
                return
            if self.path == "/v1/telemetry/subscriptions/boost":
                self.send_json(200, TELEMETRY.boost(str(payload.get("subscription_id") or ""), int(payload.get("seconds") or 900)))
                return
            acquired = SEMAPHORE.acquire(timeout=MANUAL_WAIT_SECONDS)
            if not acquired:
                self.send_json(503, {"ok": False, "message": "Conector ocupado. A solicitação não perdeu dados; tente novamente em instantes."})
                return
            try:
                if self.path == "/v1/accounts/test":
                    result = connector.handle_account(payload, sync=False)
                elif self.path == "/v1/vehicles/sync":
                    result = connector.handle_account(payload, sync=True)
                else:
                    result = connector.handle_command(payload)
                self.send_json(200, result)
            finally:
                SEMAPHORE.release()
        except (ValueError, RuntimeError) as exc:
            self.send_json(422, {"ok": False, "message": connector.clean_message(str(exc)), "connector_version": connector.CONNECTOR_VERSION})
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Unhandled connector error")
            self.send_json(500, {"ok": False, "message": "Falha interna no conector.", "connector_version": connector.CONNECTOR_VERSION})


if __name__ == "__main__":
    if not any(len(secret) >= 32 for secret in SECRETS.values()):
        LOG.error("Configure staging_secret ou production_secret antes de iniciar.")
    server = ThreadingHTTPServer(("0.0.0.0", 8094), Handler)
    server.daemon_threads = True
    TELEMETRY.start()
    LOG.info("%s listening on port 8094", SERVICE)
    try:
        server.serve_forever()
    finally:
        TELEMETRY.stop()
