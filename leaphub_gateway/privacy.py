#!/usr/bin/env python3
"""Central privacy guard for Gateway logs and diagnostics.

Identifiers are replaced by stable, irreversible aliases derived from a local
HMAC key. The key is created once under /data/security and never exported.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from pathlib import Path
from typing import Any

PRIVACY_VERSION = "1.12.18"

_KEY_PATH = Path(os.getenv("LEAPHUB_PRIVACY_KEY_PATH", "/data/security/log-privacy.key"))
_KEY: bytes | None = None


def _key() -> bytes:
    global _KEY
    if _KEY is not None:
        return _KEY
    try:
        _KEY_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if _KEY_PATH.is_file():
            value = _KEY_PATH.read_bytes()
            if len(value) >= 32:
                _KEY = value[:64]
                return _KEY
        value = os.urandom(32)
        descriptor = os.open(_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(value)
            handle.flush()
        _KEY = value
        return value
    except (OSError, PermissionError):
        # Ephemeral fallback is still non-reversible. Runtime images normally
        # have /data/security writable, so aliases remain stable across restarts.
        _KEY = os.urandom(32)
        return _KEY


def alias(kind: str, value: Any, length: int = 8) -> str:
    raw = str(value or "").strip()
    if not raw:
        return f"{kind}_unknown"
    digest = hmac.new(_key(), raw.encode("utf-8", "replace"), hashlib.sha256).hexdigest()
    return f"{kind}_{digest[: max(6, min(16, int(length)))]}"


_SECRET_KEY = r"(?:operatePassword|operation_password|password|senha|token|access_token|refresh_token|authorization|cookie|secret|api[_-]?key|certificate(?:_pem)?|private[_-]?key)"
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?9?\d{4}[-\s]?\d{4}(?!\d)")
_IP = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_MAC = re.compile(r"(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b")
_UUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
_TRACE = re.compile(r"(?i)(?<![a-z0-9])[a-f0-9]{20,64}(?![a-z0-9])")
_VIN = re.compile(r"(?i)\b[A-HJ-NPR-Z0-9]{17}\b")
_ACCOUNT = re.compile(r"(?i)\bleaphub-(?:staging|production)-account-\d+\b")
_ACCOUNT_FIELD = re.compile(r"(?i)(?P<prefix>\b(?:account_id|account|conta)\s*[=:]\s*)(?P<value>\d{1,18})\b")
_CHARGE_CONTEXT = re.compile(r"(?i)(?P<prefix>charge(?:\s+point|\s+id)?\s*(?:(?:connected|disconnected|failed|for)\s*[:=]?\s*|[:=]\s*|\s+))(?P<value>[A-Z0-9._:-]{8,80})")
_COORD_PAIR = re.compile(r"(?<!\d)(-?\d{1,2}\.\d{4,})\s*[,;/]\s*(-?\d{1,3}\.\d{4,})(?!\d)")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*\b")
_PEM = re.compile(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", re.DOTALL)


def _sub_alias(pattern: re.Pattern[str], kind: str, text: str) -> str:
    return pattern.sub(lambda match: alias(kind, match.group(0)), text)


def sanitize_log(value: Any, maximum: int = 8000) -> str:
    text = str(value or "").replace("\x00", " ")
    if "-----BEGIN" in text:
        text = _PEM.sub("[certificado protegido]", text)
    # Bearer precisa ser removido antes do filtro genérico de Authorization;
    # caso contrário apenas a palavra "Bearer" seria consumida e o token
    # permaneceria no fim da linha.
    text = _BEARER.sub("Bearer [protegido]", text)
    text = re.sub(rf"(?i)({_SECRET_KEY})\s*[=:]\s*([^&\s,;]+)", r"\1=[protegido]", text)
    text = re.sub(rf'(?i)(["\']{_SECRET_KEY}["\']\s*:\s*["\'])[^"\']*(["\'])', r"\1[protegido]\2", text)
    text = _EMAIL.sub(lambda match: alias("email", match.group(0)), text)
    text = _PHONE.sub(lambda match: alias("phone", match.group(0)), text)
    text = _ACCOUNT.sub(lambda match: alias("acct", match.group(0)), text)
    text = _ACCOUNT_FIELD.sub(
        lambda match: match.group("prefix") + alias("acct", match.group("value")), text
    )
    text = _VIN.sub(lambda match: alias("veh", match.group(0)), text)
    text = _MAC.sub(lambda match: alias("dev", match.group(0)), text)
    text = _UUID.sub(lambda match: alias("ref", match.group(0)), text)
    text = _TRACE.sub(lambda match: alias("ref", match.group(0)), text)
    text = _COORD_PAIR.sub(lambda match: alias("geo", match.group(0)), text)
    text = _IP.sub(lambda match: alias("ip", match.group(0)), text)

    def charge_replace(match: re.Match[str]) -> str:
        raw = match.group("value")
        if raw.startswith(("acct_", "veh_", "ref_", "ip_", "cp_")):
            return match.group(0)
        return match.group("prefix") + alias("cp", raw)

    text = _CHARGE_CONTEXT.sub(charge_replace, text)
    # JSON/query-string identifiers that are shorter than a VIN.
    text = re.sub(
        r'(?i)(["\']?(?:charge_id|charge_point_id|device_id|bluetooth_mac|plate|placa)["\']?\s*[=:]\s*["\']?)([^"\'&\s,;}]+)',
        lambda match: match.group(1) + alias("cp" if "charge" in match.group(1).lower() else "dev", match.group(2)),
        text,
    )
    text = " ".join(text.split())
    maximum = max(200, min(20000, int(maximum or 8000)))
    return text[:maximum] or "[mensagem protegida]"


class PrivacyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
            record.msg = sanitize_log(rendered)
            record.args = ()
            if record.exc_text:
                record.exc_text = sanitize_log(record.exc_text)
        except Exception:
            record.msg = "[mensagem protegida por falha de sanitização]"
            record.args = ()
        return True


def install_logging_privacy_filter() -> PrivacyFilter:
    root = logging.getLogger()
    existing = next((item for item in root.filters if isinstance(item, PrivacyFilter)), None)
    guard = existing or PrivacyFilter()
    if existing is None:
        root.addFilter(guard)
    for handler in root.handlers:
        if not any(isinstance(item, PrivacyFilter) for item in handler.filters):
            handler.addFilter(guard)
    return guard
