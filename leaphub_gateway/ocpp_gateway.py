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
import ipaddress
import json
import logging
import os
import re
import secrets
import signal
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GATEWAY_VERSION = "1.11.85"
IS_RAILWAY = bool(os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("RAILWAY_SERVICE_ID"))
RUNTIME_DIR = Path(os.getenv("LEAPHUB_RUNTIME_DIR", "/tmp/leaphub-ocpp" if IS_RAILWAY else "."))
BIND = os.getenv("LEAPHUB_OCPP_BIND", "0.0.0.0")
PORT = int(os.getenv("PORT") or os.getenv("LEAPHUB_OCPP_PORT", "8092"))
INTERNAL_URL = os.getenv(
    "LEAPHUB_INTERNAL_URL",
    "http://127.0.0.1:8080/beta/leap/api/internal/ocpp",
).strip()
SECRET_FILE = Path(os.getenv("LEAPHUB_GATEWAY_SECRET_FILE", str(RUNTIME_DIR / "ocpp-gateway-secret.txt")))
STATUS_FILE = Path(os.getenv("LEAPHUB_STATUS_FILE", str(RUNTIME_DIR / "ocpp-gateway-status.json")))
PID_FILE = Path(os.getenv("LEAPHUB_PID_FILE", str(RUNTIME_DIR / "ocpp-gateway.pid")))
LOG_FILE = Path(os.getenv("LEAPHUB_LOG_FILE", str(RUNTIME_DIR / "ocpp-gateway.log")))
SERVICE_NAME = os.getenv("RAILWAY_SERVICE_NAME", os.getenv("LEAPHUB_SERVICE_NAME", "leaphub-ocpp"))
DEPLOYMENT_ID = os.getenv("RAILWAY_DEPLOYMENT_ID", "")
RAILWAY_ENVIRONMENT = os.getenv("RAILWAY_ENVIRONMENT_NAME", "")
PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
ENVIRONMENT_LABEL = os.getenv("LEAPHUB_ENVIRONMENT", "staging")
GATEWAY_MODE = os.getenv("LEAPHUB_GATEWAY_MODE", "home_assistant_tunnel")
GATEWAY_PROVIDER = os.getenv("LEAPHUB_GATEWAY_PROVIDER", "home_assistant_tunnel")
MAX_FRAME_BYTES = int(os.getenv("LEAPHUB_OCPP_MAX_FRAME_BYTES", str(1024 * 1024)))
COMMAND_POLL_SECONDS = float(os.getenv("LEAPHUB_OCPP_COMMAND_POLL", "1.5"))
MAX_CONNECTIONS = max(1, int(os.getenv("LEAPHUB_OCPP_MAX_CONNECTIONS", "1000")))
MAX_CONNECTIONS_PER_IP = max(1, int(os.getenv("LEAPHUB_OCPP_MAX_CONNECTIONS_PER_IP", "50")))
AUTH_FAILURE_WINDOW_SECONDS = max(60, int(os.getenv("LEAPHUB_OCPP_AUTH_WINDOW", "300")))
AUTH_FAILURE_LIMIT = max(3, int(os.getenv("LEAPHUB_OCPP_AUTH_FAILURE_LIMIT", "20")))
AUTH_BLOCK_SECONDS = max(60, int(os.getenv("LEAPHUB_OCPP_AUTH_BLOCK_SECONDS", "600")))
STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
DIAGNOSTIC_WINDOW_SECONDS = 180
DIAGNOSTIC_NONCES: dict[str, float] = {}
STATUS_API_LAST_ERROR = ""
STATUS_API_LAST_LOG_AT = 0.0


for path in (STATUS_FILE, PID_FILE, LOG_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=os.getenv("LEAPHUB_OCPP_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
LOG = logging.getLogger("leaphub.ocpp")


def load_secret() -> str:
    secret = os.getenv("LEAPHUB_GATEWAY_SECRET", "").strip()
    if not secret:
        try:
            secret = SECRET_FILE.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(
                "Gateway secret not available. Set LEAPHUB_GATEWAY_SECRET or provide the secret file."
            ) from exc
    if len(secret) < 32:
        raise RuntimeError("Gateway secret is invalid.")
    return secret


GATEWAY_SECRET = load_secret()


def api_call(payload: dict[str, Any], timeout: float = 20.0) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    path = urllib.parse.urlsplit(INTERNAL_URL).path or "/api/internal/ocpp"
    canonical = f"POST\n{path}\n{timestamp}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode("utf-8")
    signature = hmac.new(GATEWAY_SECRET.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        INTERNAL_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-LeapHub-Timestamp": timestamp,
            "X-LeapHub-Nonce": nonce,
            "X-LeapHub-Signature": signature,
            "User-Agent": f"LeapHub-OCPP-Gateway/{GATEWAY_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", "replace")
        raise RuntimeError(f"Internal API rejected request ({exc.code}): {detail[:400]}") from exc
    except OSError as exc:
        raise RuntimeError(f"Internal API unavailable: {exc}") from exc
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict) or not decoded.get("ok"):
        raise RuntimeError(str(decoded.get("message", "Internal API returned an invalid response.")))
    return decoded


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
        "gateway_mode": GATEWAY_MODE,
        "provider": GATEWAY_PROVIDER,
        "connections": len(CONNECTIONS),
        "max_connections": MAX_CONNECTIONS,
        "started_at": STARTED_AT,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def verify_diagnostic_signature(method: str, path: str, headers: dict[str, str]) -> None:
    timestamp = headers.get("x-leaphub-timestamp", "").strip()
    nonce = headers.get("x-leaphub-nonce", "").strip().lower()
    environment = headers.get("x-leaphub-environment", "").strip().lower()
    signature = headers.get("x-leaphub-signature", "").strip().lower()
    if environment != ENVIRONMENT_LABEL.lower():
        raise PermissionError("Invalid environment")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > DIAGNOSTIC_WINDOW_SECONDS:
        raise PermissionError("Expired signature")
    if re.fullmatch(r"[a-f0-9]{32,128}", nonce) is None:
        raise PermissionError("Invalid nonce")
    if re.fullmatch(r"[a-f0-9]{64}", signature) is None:
        raise PermissionError("Missing signature")
    body_hash = hashlib.sha256(b"").hexdigest()
    canonical = f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}".encode("utf-8")
    expected = hmac.new(GATEWAY_SECRET.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
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
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    remote_ip: str
    writer_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_calls: dict[str, asyncio.Future[list[Any]]] = field(default_factory=dict)
    closed: bool = False

    async def send_json(self, value: list[Any]) -> None:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        async with self.writer_lock:
            await write_frame(self.writer, 0x1, raw)

    async def send_call(self, action: str, payload: dict[str, Any], timeout: float = 35.0) -> list[Any]:
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
        try:
            result = await asyncio.to_thread(
                api_call,
                {
                    "action": "ocpp_call",
                    "identity": self.identity,
                    "message_id": message_id,
                    "ocpp_action": action,
                    "payload": payload,
                },
            )
            if isinstance(result.get("call_error"), dict):
                error = result["call_error"]
                await self.send_json(
                    [
                        4,
                        message_id,
                        str(error.get("code", "InternalError")),
                        str(error.get("description", "Request failed.")),
                        error.get("details") if isinstance(error.get("details"), dict) else {},
                    ]
                )
            else:
                response_payload = result.get("response_payload")
                await self.send_json([3, message_id, response_payload if isinstance(response_payload, dict) else {}])
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Failed to process %s from %s", action, self.identity)
            await self.send_json([4, message_id, "InternalError", "Request could not be processed.", {}])

    async def command_loop(self) -> None:
        while not self.closed:
            await asyncio.sleep(COMMAND_POLL_SECONDS)
            try:
                result = await asyncio.to_thread(
                    api_call,
                    {"action": "fetch_commands", "identity": self.identity},
                    10.0,
                )
                commands = result.get("commands")
                if not isinstance(commands, list):
                    continue
                for command in commands:
                    if not isinstance(command, dict):
                        continue
                    await self.execute_command(command)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOG.warning("Command polling failed for %s: %s", self.identity, exc)

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
            LOG.error("Could not report command %s result: %s", command_id, exc)

    async def ping_loop(self) -> None:
        while not self.closed:
            await asyncio.sleep(30)
            async with self.writer_lock:
                await write_frame(self.writer, 0x9, os.urandom(4))

    async def run(self) -> None:
        command_task = asyncio.create_task(self.command_loop())
        ping_task = asyncio.create_task(self.ping_loop())
        fragmented_opcode: int | None = None
        fragmented = bytearray()
        try:
            while True:
                fin, opcode, payload = await read_frame(self.reader)
                if opcode == 0x8:
                    async with self.writer_lock:
                        await write_frame(self.writer, 0x8, payload[:125])
                    break
                if opcode == 0x9:
                    async with self.writer_lock:
                        await write_frame(self.writer, 0xA, payload[:125])
                    continue
                if opcode == 0xA:
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
    candidates = [
        headers.get("cf-connecting-ip", ""),
        headers.get("x-real-ip", ""),
        headers.get("x-forwarded-for", "").split(",", 1)[0].strip(),
        peer_ip,
    ]
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
        if len(CONNECTIONS) >= MAX_CONNECTIONS:
            await http_error(writer, 503, "Service Unavailable")
            return
        if ACTIVE_BY_IP.get(remote_ip, 0) >= MAX_CONNECTIONS_PER_IP:
            await http_error(writer, 429, "Too Many Requests")
            return

        username, password = basic_credentials(headers)
        if username and username != identity:
            record_auth_failure(remote_ip)
            await http_error(writer, 401, "Unauthorized")
            return
        authorization = await asyncio.to_thread(
            api_call,
            {
                "action": "authorize_connection",
                "identity": identity,
                "password": password,
                "remote_ip": remote_ip,
            },
        )
        if not authorization.get("accepted"):
            record_auth_failure(remote_ip)
            await http_error(writer, 401, "Unauthorized")
            return
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
        connection = ChargePointConnection(identity, reader, writer, remote_ip)
        CONNECTIONS[identity] = connection
        ACTIVE_BY_IP[remote_ip] = ACTIVE_BY_IP.get(remote_ip, 0) + 1
        LOG.info("Charge point connected: %s", identity)
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
            try:
                await asyncio.to_thread(api_call, {"action": "disconnect", "identity": identity}, 8.0)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("Could not record disconnect for %s: %s", identity, exc)
            LOG.info("Charge point disconnected: %s", identity)


async def status_loop() -> None:
    while not STOP_EVENT.is_set():
        status = {
            "pid": os.getpid(),
            "connections": len(CONNECTIONS),
            "active_ips": len(ACTIVE_BY_IP),
            "blocked_ips": len(AUTH_BLOCKED_UNTIL),
            "auth_failure_ips": len(AUTH_FAILURES),
            "max_connections": MAX_CONNECTIONS,
            "port": PORT,
            "started_at": STARTED_AT,
            "gateway_mode": GATEWAY_MODE,
            "provider": GATEWAY_PROVIDER,
            "service_name": SERVICE_NAME,
            "deployment_id": DEPLOYMENT_ID,
            "railway_environment": RAILWAY_ENVIRONMENT,
            "public_domain": PUBLIC_DOMAIN,
            "version": GATEWAY_VERSION,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        temporary = STATUS_FILE.with_suffix(STATUS_FILE.suffix + ".tmp")
        temporary.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
        temporary.replace(STATUS_FILE)
        try:
            await asyncio.to_thread(api_call, {"action": "gateway_status", **status}, 8.0)
        except Exception as exc:  # noqa: BLE001
            # Não inunda o log a cada 15 segundos quando a API interna está
            # temporariamente indisponível. Erros novos são exibidos na hora;
            # o mesmo erro volta a ser lembrado no máximo a cada cinco minutos.
            global STATUS_API_LAST_ERROR, STATUS_API_LAST_LOG_AT
            message = str(exc)
            now = time.monotonic()
            if message != STATUS_API_LAST_ERROR or now - STATUS_API_LAST_LOG_AT >= 300:
                LOG.warning("Gateway status API failed: %s", message)
                STATUS_API_LAST_ERROR = message
                STATUS_API_LAST_LOG_AT = now
            else:
                LOG.debug("Gateway status API ainda indisponível: %s", message)
        try:
            await asyncio.wait_for(STOP_EVENT.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass


async def main() -> None:
    if GATEWAY_MODE != "local" and not INTERNAL_URL.lower().startswith("https://"):
        raise RuntimeError("LEAPHUB_INTERNAL_URL must use https:// outside local mode.")
    PID_FILE.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    try:
        os.chmod(PID_FILE, 0o600)
    except OSError:
        pass
    server = await asyncio.start_server(handle_client, BIND, PORT, limit=MAX_FRAME_BYTES + 65536)
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    LOG.info("Leap Hub OCPP gateway listening on %s", sockets)
    status_task = asyncio.create_task(status_loop())
    async with server:
        await STOP_EVENT.wait()
    status_task.cancel()
    try:
        await status_task
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
