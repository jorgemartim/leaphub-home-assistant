#!/usr/bin/env python3
"""Read-only, redacted Leapmotor drivingRecord probe for Gateway 1.12.128.

The caller MUST provide an already-authenticated persistent client. This module
never logs in, refreshes a token, creates a second client, or returns raw vehicle
values. It proves the signed begin/end millisecond window on a real C10 before
any response field is promoted to an ``official_*`` semantic alias.
"""
from __future__ import annotations

import math
import re
import time
from typing import Any
from urllib.parse import quote

from leapmotor_api.crypto import build_signed_headers

PROBE_VERSION = "1.12.128"
WINDOW_PATH = "/carownerservice/oversea/drivingRecord/v1/mileage/energy/detail"
MAX_WINDOW_MS = 7 * 24 * 60 * 60 * 1000
MIN_MILLISECONDS = 1_000_000_000_000
PARSE_LABEL = "windowed mileage energy detail"
_SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,31}$")
_UUID_KEY = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
_LONG_HEX_KEY = re.compile(r"^[0-9a-fA-F]{16,}$")
_LONG_DIGIT_RUN = re.compile(r"\d{8,}")
_OPAQUE_PREFIX = re.compile(r"^(?:ref|id|vin|trip|record|request|remote|token)[_.:-][A-Za-z0-9_-]{8,}$", re.IGNORECASE)


def _as_millis(value: Any, label: str) -> int:
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} precisa ser um timestamp inteiro em milissegundos.") from exc
    if result < MIN_MILLISECONDS:
        raise ValueError(f"{label} precisa estar em milissegundos, não segundos.")
    return result


def normalize_window(payload: dict[str, Any]) -> tuple[int, int]:
    begin_raw = payload.get("begintime_ms", payload.get("begintime"))
    end_raw = payload.get("endtime_ms", payload.get("endtime"))
    begin_ms = _as_millis(begin_raw, "begintime")
    end_ms = _as_millis(end_raw, "endtime")
    if end_ms <= begin_ms:
        raise ValueError("endtime precisa ser posterior a begintime.")
    if end_ms - begin_ms > MAX_WINDOW_MS:
        raise ValueError("A sonda aceita no máximo 7 dias por leitura.")
    return begin_ms, end_ms


def _shape_key(value: Any) -> str:
    """Keep ordinary schema names while redacting value-like or opaque keys."""
    text = str(value or "")
    if not _SAFE_KEY.fullmatch(text):
        return "<dynamic-key>"
    if len(text) == 17 and text == text.upper() and text.isalnum():
        return "<dynamic-key>"
    if text.isdigit() or _UUID_KEY.fullmatch(text) or _LONG_HEX_KEY.fullmatch(text):
        return "<dynamic-key>"
    if _LONG_DIGIT_RUN.search(text) or _OPAQUE_PREFIX.fullmatch(text):
        return "<dynamic-key>"
    return text


def describe_shape(value: Any, depth: int = 0, max_depth: int = 5) -> Any:
    """Return schema/shape only; never copy raw user values into diagnostics."""
    if depth >= max_depth:
        return type(value).__name__
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:80]:
            safe_key = _shape_key(key)
            if safe_key == "<dynamic-key>" and safe_key in result:
                continue
            result[safe_key] = describe_shape(item, depth + 1, max_depth)
        return result
    if isinstance(value, (list, tuple)):
        if not value:
            return {"kind": "list", "items": "empty"}
        return {"kind": "list", "items": "present", "sample_shape": describe_shape(value[0], depth + 1, max_depth)}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    return type(value).__name__


def _body_size(value: Any) -> int:
    if isinstance(value, bytes):
        return len(value)
    return len(str(value or "").encode("utf-8", errors="replace"))


def _shape_nodes(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + sum(_shape_nodes(item) for item in value.values())
    if isinstance(value, list):
        return 1 + sum(_shape_nodes(item) for item in value)
    return 1



_C10_DAILY_SIGNATURE = frozenset({
    "totalAccumulatedMileageMile",
    "totalmileageMile",
    "totalAccumulatedMileage",
    "totalmileage",
    "deliveryDays",
    "totalEnergy",
    "detail",
})


def _mapped_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or abs(number) > 1_000_000_000_000:
        return None
    if isinstance(value, int):
        return int(value)
    return number


def _mapped_text(value: Any, limit: int = 80) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > max(1, min(160, int(limit))) or not text.isprintable():
        return None
    return text


def map_c10_daily_values(parsed: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Map only the exact C10 daily/cumulative fields proven in field homologation.

    Values keep their cloud scale/unit intentionally unverified. Unknown keys,
    references, identifiers and nested raw response data are never copied.
    """
    if not isinstance(parsed, dict):
        return None, []
    data = parsed.get("data")
    if not isinstance(data, dict) or not _C10_DAILY_SIGNATURE.issubset(set(data.keys())):
        return None, []

    totals: dict[str, Any] = {}
    mapped_fields: list[str] = []
    numeric_totals = {
        "totalAccumulatedMileage": "total_accumulated_mileage_raw",
        "totalmileage": "total_mileage_raw",
        "deliveryDays": "delivery_days",
        "totalEnergy": "total_energy_raw",
    }
    text_totals = {
        "totalAccumulatedMileageMile": "total_accumulated_mileage_mile_text",
        "totalmileageMile": "total_mileage_mile_text",
    }
    for source, target in numeric_totals.items():
        value = _mapped_number(data.get(source))
        if value is not None:
            totals[target] = value
            mapped_fields.append(f"data.{source}")
    for source, target in text_totals.items():
        value = _mapped_text(data.get(source))
        if value is not None:
            totals[target] = value
            mapped_fields.append(f"data.{source}")

    days: list[dict[str, Any]] = []
    detail = data.get("detail")
    if isinstance(detail, list):
        for item in detail[:16]:
            if not isinstance(item, dict):
                continue
            day: dict[str, Any] = {}
            day_text = _mapped_text(item.get("day"), 40)
            if day_text is not None:
                day["day"] = day_text
                mapped_fields.append("data.detail[].day")
            for source, target in (
                ("xDay", "x_day"),
                ("currentMileage", "current_mileage_raw"),
                ("accumulatedMileage", "accumulated_mileage_raw"),
                ("accumulatedEnergyConsume", "accumulated_energy_consume_raw"),
            ):
                value = _mapped_number(item.get(source))
                if value is not None:
                    day[target] = value
                    mapped_fields.append(f"data.detail[].{source}")
            mile_text = _mapped_text(item.get("accumulatedMileageMile"))
            if mile_text is not None:
                day["accumulated_mileage_mile_text"] = mile_text
                mapped_fields.append("data.detail[].accumulatedMileageMile")
            if day:
                days.append(day)

    return {
        "schema_version": 1,
        "unit_status": "unverified",
        "totals": totals,
        "days": days,
    }, sorted(set(mapped_fields))

def probe_windowed_mileage_energy(client: Any, *, vin: str, begin_ms: int, end_ms: int) -> dict[str, Any]:
    """Perform exactly one signed POST and return only redacted response shape."""
    vin = str(vin or "").strip().upper()
    if len(vin) != 17 or not vin.isalnum():
        raise ValueError("VIN indisponível para a sonda oficial.")
    if end_ms <= begin_ms or end_ms - begin_ms > MAX_WINDOW_MS:
        raise ValueError("Janela oficial inválida.")
    body_params = {"begintime": str(begin_ms), "endtime": str(end_ms)}
    headers = build_signed_headers(
        sign_key=client.sign_key,
        device_id=client.device_id,
        vin=vin,
        language=client.language,
        body_params=body_params,
    ).to_dict()
    headers.update(client._auth_headers())
    body = f"endtime={end_ms}&begintime={begin_ms}&vin={quote(vin, safe='')}"
    started = time.monotonic()
    response = client._post(path=WINDOW_PATH, headers=headers, data=body, cert=client.account_cert)
    response_size = _body_size(response.get("body"))
    try:
        parsed = client._parse_api_body(response["status_code"], response["body"], PARSE_LABEL)
    finally:
        last_results = getattr(client, "last_api_results", None)
        if isinstance(last_results, dict):
            last_results.pop(PARSE_LABEL, None)
    shape = describe_shape(parsed)
    official_daily, mapped_fields = map_c10_daily_values(parsed)
    result = {
        "ok": True,
        "probe_version": PROBE_VERSION,
        "endpoint": "drivingRecord/mileage/energy/detail",
        "http_status": int(response.get("status_code") or 0),
        "duration_ms": int(round((time.monotonic() - started) * 1000)),
        "response_body_bytes": int(response_size),
        "response_shape_nodes": int(_shape_nodes(shape)),
        "window": {"begintime_ms": int(begin_ms), "endtime_ms": int(end_ms), "duration_ms": int(end_ms - begin_ms)},
        "response_shape": shape,
        "raw_values_included": False,
        "raw_response_included": False,
        "mapped_values_included": official_daily is not None,
        "mapped_fields": mapped_fields,
        "mapping_status": "mapped_c10_daily_raw" if official_daily is not None else "awaiting_c10_daily_shape",
    }
    if official_daily is not None:
        result["official_daily"] = official_daily
    return result
