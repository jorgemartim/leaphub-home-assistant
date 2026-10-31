#!/usr/bin/env python3
"""Read-only, redacted Leapmotor drivingRecord probe for Gateway 1.12.130.

The caller MUST provide an already-authenticated persistent client. This module
never logs in, refreshes a token, creates a second client, or returns raw vehicle
values. It proves the signed begin/end millisecond window on a real C10 before
any response field is promoted to an ``official_*`` semantic alias.
"""
from __future__ import annotations

import math
import json
import re
import time
from typing import Any
from urllib.parse import quote

from leapmotor_api.crypto import build_signed_headers
from leapmotor_api.exceptions import LeapmotorApiError

PROBE_VERSION = "1.12.135"
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

# Separate, versioned contract: never interpret driving totals as charging kWh.
CHARGING_PROBE_VERSION = "1.12.135"
CHARGING_PATH = "/carownerservice/charge/daily/detail/page"
CHARGING_PAGE_SIZE = 25
CHARGING_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _charging_numeric_code(value: Any) -> int | None:
    if type(value) is int and abs(value) <= 99_999_999:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d{1,8}", value, flags=re.ASCII):
        return int(value)
    return None


def _charging_message_class(body: Any) -> str:
    """Only a closed hint leaves the reader; never return external message text."""
    value = body.get("message") if isinstance(body, dict) else None
    if not isinstance(value, str):
        return "missing"
    value = value[:4096].strip().lower()
    if not value:
        return "empty"
    for category, markers in (
        ("auth", ("token expired", "session expired", "invalid token", "token is invalid", "expired token", "not logged in", "not login", "登录已过期", "未登录")),
        ("access", ("no such permission", "permission denied", "access denied", "no permission", "forbidden", "无权限", "没有权限")),
        ("signature", ("invalid signature", "signature error", "sign error", "sign invalid", "signature verification failed", "签名错误", "签名验证失败")),
        ("route", ("no handler found", "no route", "not found", "interface does not exist", "接口不存在", "接口不存在或已下线")),
        ("request", ("invalid parameter", "parameter error", "missing parameter", "参数错误", "参数异常")),
        ("temporary", ("too many requests", "service unavailable", "system busy", "系统繁忙", "请求过于频繁")),
    ):
        if any(marker in value for marker in markers):
            return category
    return "unrecognized"


def _charging_content(response: dict[str, Any] | None) -> tuple[str | None, Any, dict[str, Any]]:
    """Inspect content internally; expose only fixed format classes and key presence."""
    raw = response.get("body") if isinstance(response, dict) else None
    headers = response.get("headers") if isinstance(response, dict) else None
    mime = ""
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() == "content-type" and isinstance(value, str):
                mime = value[:128].lower().split(";", 1)[0].strip()
                break
    content_type = ("missing" if not mime else "json" if mime == "application/json" or mime.endswith("+json")
                    else "html" if mime in {"text/html", "application/xhtml+xml"} else "text" if mime == "text/plain" else "other")
    bom = isinstance(raw, str) and raw.startswith("\ufeff")
    size = len(raw.encode("utf-8", errors="replace")) if isinstance(raw, str) else 0
    bucket = "empty" if size == 0 else "small" if size <= 4096 else "medium" if size <= 65536 else "large" if size <= CHARGING_MAX_RESPONSE_BYTES else "oversized"
    text = raw.removeprefix("\ufeff") if isinstance(raw, str) and size <= CHARGING_MAX_RESPONSE_BYTES else None
    value = None
    valid_json = False
    if text is not None:
        try:
            value = json.loads(text)
            valid_json = True
        except (ValueError, TypeError, RecursionError):
            pass
    if not isinstance(raw, str):
        body_format = "missing"
    elif size > CHARGING_MAX_RESPONSE_BYTES:
        body_format = "oversized"
    elif text is not None and not text.strip():
        body_format = "empty"
    elif valid_json:
        body_format = "json_object" if isinstance(value, dict) else "json_list" if isinstance(value, list) else "json_null" if value is None else "json_scalar"
    elif text is not None and text.lstrip().lower().startswith(("<!doctype html", "<html")):
        body_format = "html"
    elif text is not None and text.lstrip().startswith("<"):
        body_format = "markup"
    else:
        body_format = "non_json"
    known_keys = [key for key in ("code", "result", "data", "message", "status", "error", "success")
                  if isinstance(value, dict) and key in value]
    envelope_status = value.get("status") if isinstance(value, dict) else None
    envelope_status = envelope_status if type(envelope_status) is int and 100 <= envelope_status <= 599 else None
    profile = {"body_format": body_format, "content_type": content_type, "size_bucket": bucket,
               "utf8_bom": bom, "known_keys": known_keys, "envelope_status": envelope_status,
               "result_code": _charging_numeric_code(value.get("result")) if isinstance(value, dict) else None,
               "message_class": _charging_message_class(value)}
    return text, value, profile


def _charging_failure(response: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    """Only bounded status codes and fixed shape enums leave the cloud reader."""
    status = response.get("status_code") if isinstance(response, dict) else None
    status = status if type(status) is int and 100 <= status <= 599 else None
    _text, body, profile = _charging_content(response)
    raw_code = body.get("code") if isinstance(body, dict) else None
    # Some error envelopes use result/message rather than code/message. This
    # fallback is diagnostic only: result=0 never authorizes a successful read.
    code = _charging_numeric_code(raw_code)
    if isinstance(body, dict) and "code" not in body:
        code = profile["result_code"]
    def shape(value: Any) -> str:
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "list"
        return "missing" if value is None else "scalar"
    data = body.get("data") if isinstance(body, dict) else None
    records = data.get("list") if isinstance(data, dict) else None
    diagnostic = {"cloud_http_status": status, "cloud_code": code,
                  "response_format": shape(body), "data_format": shape(data), "records_format": shape(records)}
    if reason == "charging_response_invalid":
        if status == 401 or profile["message_class"] == "auth":
            reason = "charging_auth_unavailable"
        elif status == 403 or profile["message_class"] == "access":
            reason = "charging_access_denied"
        elif status == 429 or (status is not None and status >= 500) or profile["message_class"] == "temporary":
            reason = "charging_cloud_temporary"
        elif (isinstance(body, dict) and raw_code is not None and raw_code != 0) or (code is not None and code != 0):
            reason = "charging_cloud_rejected"
    temporary = reason in {"charging_transport_error", "charging_cloud_temporary", "charging_auth_unavailable"}
    result = {"ok": False, "temporary": temporary, "reason": reason,
              "probe_kind": "charging_history", "probe_version": CHARGING_PROBE_VERSION,
              "diagnostic": diagnostic, "response_profile": profile, "raw_response_included": False}
    if temporary:
        result["retry_after_seconds"] = 20
    return result


def normalize_charging_options(payload: dict[str, Any]) -> tuple[int, int]:
    page = payload.get("page_num", 1)
    offset = payload.get("utc_offset_minutes", 0)
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 5:
        raise ValueError("A leitura aceita páginas de 1 a 5.")
    if isinstance(offset, bool) or not isinstance(offset, int) or not -720 <= offset <= 840 or offset % 15:
        raise ValueError("Fuso inválido para o histórico de recarga.")
    return page, offset


def probe_charging_history(client: Any, *, vin: str, begin_ms: int, end_ms: int,
                           page_num: int = 1, utc_offset_minutes: int = 0,
                           request_profile: str = "sdk_dates") -> dict[str, Any]:
    """Exactly one authenticated read; no login/refresh/retry or raw location/VIN in result."""
    from datetime import datetime, timedelta, timezone
    begin_ms, end_ms = normalize_window({"begintime_ms": begin_ms, "endtime_ms": end_ms})
    if request_profile not in {"sdk_dates", "epoch_seconds"}:
        raise ValueError("Formato de consulta de recarga inválido.")
    page_num, utc_offset_minutes = normalize_charging_options({"page_num": page_num, "utc_offset_minutes": utc_offset_minutes})
    vin = str(vin or "").strip().upper()
    if len(vin) != 17 or not vin.isalnum():
        raise ValueError("VIN indisponível para o histórico de recarga.")
    zone = timezone(timedelta(minutes=utc_offset_minutes))
    sign = "+" if utc_offset_minutes >= 0 else "-"
    hours, minutes = divmod(abs(utc_offset_minutes), 60)
    start = datetime.fromtimestamp(begin_ms / 1000, zone).date().isoformat()
    end = datetime.fromtimestamp(end_ms / 1000, zone).date().isoformat()
    zone_name = f"GMT{sign}{hours:02d}:{minutes:02d}"
    # Keep the signing strings identical to SDK 0.3.2 / 0.6.0; JSON page values are ints.
    signed = {"vin": vin, "timeZone": zone_name, "startTime": start, "endTime": end,
              "pageNum": str(page_num), "pageSize": str(CHARGING_PAGE_SIZE)}
    headers = build_signed_headers(sign_key=client.sign_key, device_id=client.device_id,
                                   language=client.language, body_params=signed).to_dict()
    headers.update(client._auth_headers())
    headers["Content-Type"] = "application/json"
    body = dict(signed, pageNum=page_num, pageSize=CHARGING_PAGE_SIZE)
    if request_profile == "epoch_seconds":
        # Current history contract uses Unix seconds and string pagination.
        # Sign exactly these wire values; do not sign the SDK's date/timeZone body.
        body = {"vin": vin, "startTime": str(begin_ms // 1000),
                "endTime": str((end_ms + 999) // 1000),
                "pageNum": str(page_num), "pageSize": str(CHARGING_PAGE_SIZE)}
        headers = build_signed_headers(sign_key=client.sign_key, device_id=client.device_id,
                                       language=client.language, body_params=body).to_dict()
        headers.update(client._auth_headers())
        headers["Content-Type"] = "application/json"
    label = "charging history bounded read"
    response = None
    try:
        response = client._post_json(path=CHARGING_PATH, headers=headers, json_body=body, cert=client.account_cert)
        parse_body, _value, _profile = _charging_content(response)
        if parse_body is None or _profile["body_format"] not in {"json_object", "json_list", "json_null", "json_scalar"}:
            return _charging_failure(response, "charging_response_invalid")
        try:
            if request_profile == "epoch_seconds" and isinstance(_value, dict):
                codes = [_value[key] for key in ("code", "result") if key in _value]
                if not codes or any(type(code) is not int or code != 0 for code in codes):
                    return _charging_failure(response, "charging_response_invalid")
                # A result envelope is accepted only with an explicit zero and
                # the full expected data.list shape. Bare result=0 is not success.
                if not isinstance(_value.get("data"), dict) or not isinstance(_value["data"].get("list"), list):
                    return _charging_failure(response, "charging_shape_unavailable")
                parse_body = json.dumps(dict(_value, code=0))
            parsed = client._parse_api_body(response["status_code"], parse_body, label)
        except (LeapmotorApiError, AttributeError, TypeError, ValueError):
            return _charging_failure(response, "charging_response_invalid")
    except LeapmotorApiError:
        return _charging_failure(response, "charging_response_invalid" if response is not None else "charging_transport_error")
    finally:
        results = getattr(client, "last_api_results", None)
        if isinstance(results, dict):
            results.pop(label, None)
    data = parsed.get("data") if isinstance(parsed, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        return _charging_failure(response, "charging_shape_unavailable")
    raw = data["list"]
    records = []; invalid = 0; outside = 0; seen: set[tuple[int, int, str, float]] = set()
    for row in raw[:CHARGING_PAGE_SIZE]:
        if not isinstance(row, dict):
            invalid += 1
            continue
        try:
            if "vin" in row and row["vin"] != vin:
                raise ValueError("Registro de outro veículo.")
            a = _as_millis(row.get("chargeEarliestTs", row.get("chargeGunStartTs")), "início")
            b = _as_millis(row.get("chargeLatestTs", row.get("chargeGunEndTs")), "fim")
            value = row.get("chargeInEnergy")
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError("Energia inválida.")
            kwh = float(value)
            if not math.isfinite(kwh) or kwh < 0 or kwh > 500 or b <= a or b - a > MAX_WINDOW_MS:
                raise ValueError("Registro inválido.")
        except (TypeError, ValueError, OverflowError):
            invalid += 1
            continue
        if b <= begin_ms or a >= end_ms:
            outside += 1
            continue
        kind = {"1": "ac", "2": "dc", "SLOW": "ac", "FAST": "dc"}.get(str(row.get("chargeType")).upper(), "unknown")
        key = (a, b, kind, kwh)
        if key in seen:
            continue
        seen.add(key)
        records.append({"started_at_ms": a, "ended_at_ms": b, "energy_kwh": kwh, "charging_type": kind,
                        "crosses_window": a < begin_ms or b > end_ms})
    records.sort(key=lambda row: (row["started_at_ms"], row["ended_at_ms"]))
    return {"ok": True, "probe_kind": "charging_history", "probe_version": CHARGING_PROBE_VERSION,
            "raw_response_included": False, "charging_history": {
                "schema_version": 1, "source": "leapmotor_cloud", "unit": "kWh",
                "window": {"begintime_ms": begin_ms, "endtime_ms": end_ms},
                "page_num": page_num, "page_size": CHARGING_PAGE_SIZE, "has_more_possible": len(raw) >= CHARGING_PAGE_SIZE,
                "records": records, "invalid_records": invalid, "out_of_window": outside,
                "response_truncated": len(raw) > CHARGING_PAGE_SIZE}}
