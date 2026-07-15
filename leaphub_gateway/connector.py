#!/usr/bin/env python3
"""Leap Hub local connector for telemetry and safeguarded remote commands.

Reads a single JSON request from stdin and writes a single JSON response to stdout.
Credentials never appear in command-line arguments or environment variables.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

CONNECTOR_VERSION = "1.11.62"
MAX_INPUT_BYTES = 1024 * 1024

COMMAND_METHODS: dict[str, str] = {
    "lock": "lock_vehicle",
    "unlock": "unlock_vehicle",
    "find_car": "find_vehicle",
    "trunk_open": "open_trunk",
    "trunk_close": "close_trunk",
    "windows_open": "open_windows",
    "windows_close": "close_windows",
    "sunshade_open": "open_sunshade",
    "sunshade_close": "close_sunshade",
    "climate_on": "ac_on",
    "climate_off": "ac_off",
    "quick_cool": "quick_cool",
    "quick_heat": "quick_heat",
    "windshield_defrost": "windshield_defrost",
    "battery_preheat_on": "battery_preheat",
    "battery_preheat_off": "battery_preheat_off",
    "start_charging": "start_charging",
    "stop_charging": "stop_charging",
    "unlock_charger": "unlock_charger",
    "set_charge_limit": "set_charge_limit",
    "send_destination": "send_destination",
}


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=json_default), flush=True)
    raise SystemExit(exit_code)


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return asdict(value)
    return str(value)


def clean_message(message: str) -> str:
    text = " ".join(str(message).replace("\x00", " ").split())
    for marker in ("-----BEGIN", "-----END"):
        if marker in text:
            return "Falha de autenticação ou certificado inválido."
    return text[:900] or "Falha desconhecida no conector."


def package_version() -> str | None:
    try:
        return version("leapmotor-api")
    except PackageNotFoundError:
        return None


def read_request() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Entrada acima do limite permitido.")
    if not raw:
        return {"action": sys.argv[1] if len(sys.argv) > 1 else "health", "payload": {}}
    request = json.loads(raw.decode("utf-8"))
    if not isinstance(request, dict):
        raise ValueError("Requisição inválida.")
    return request


def require_text(payload: dict[str, Any], key: str, label: str, max_length: int) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"Informe {label}.")
    if len(value) > max_length:
        raise ValueError(f"{label.capitalize()} excede o limite permitido.")
    return value


def validate_pem(value: str, labels: tuple[str, ...], label: str) -> str:
    if "\x00" in value or len(value.encode("utf-8")) > 160 * 1024:
        raise ValueError(f"{label.capitalize()} inválido.")
    if not any(f"-----BEGIN {item}-----" in value for item in labels):
        raise ValueError(f"{label.capitalize()} não contém um bloco PEM aceito.")
    return value


def secure_temp_directory() -> Path:
    base_value = os.environ.get("LEAPHUB_CONNECTOR_TMP", "").strip()
    base = Path(base_value) if base_value else None
    if base is not None:
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(base, 0o700)
    path = Path(tempfile.mkdtemp(prefix="request-", dir=str(base) if base else None))
    os.chmod(path, 0o700)
    return path


def write_secret(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            if not content.endswith("\n"):
                handle.write("\n")
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def value_of(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def attribute(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "on", "open", "opened"}:
        return True
    if lowered in {"false", "0", "no", "off", "closed", "close"}:
        return False
    return None


def numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value_of(value)).strip().replace("\u00a0", " ")
    if not text:
        return None
    normalized = text.replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    else:
        normalized = normalized.replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", normalized)
    if match is None:
        return None
    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def first_numeric(*values: Any) -> float | None:
    for value in values:
        parsed = numeric(value)
        if parsed is not None:
            return parsed
    return None


def first_text(*values: Any, max_length: int = 120) -> str | None:
    for value in values:
        parsed = text_value(value, max_length)
        if parsed:
            return parsed
    return None


def iso_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    return datetime.now().astimezone().isoformat()


def optional_timestamp(value: Any) -> str | None:
    """Normalize optional cloud timestamps without inventing a current time."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.astimezone().isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp).astimezone().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = text_value(value, 100)
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate).isoformat()
    except ValueError:
        pass
    for pattern in (
        "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H%M%S",
    ):
        try:
            return datetime.strptime(text[:19], pattern).isoformat()
        except ValueError:
            continue
    return None


def plain_data(value: Any, depth: int = 0) -> Any:
    if depth > 8 or value is None or isinstance(value, (str, int, float, bool, datetime, date, Enum)):
        return value_of(value)
    if is_dataclass(value):
        return plain_data(asdict(value), depth + 1)
    if isinstance(value, dict):
        return {str(key): plain_data(item, depth + 1) for key, item in list(value.items())[:300]}
    if isinstance(value, (list, tuple, set)):
        return [plain_data(item, depth + 1) for item in list(value)[:300]]
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        try:
            return plain_data(value.model_dump(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return plain_data(vars(value), depth + 1)
    return text_value(value, 500)


def redacted_cloud_raw(value: Any, depth: int = 0) -> Any:
    """Preserve unknown cloud signals while removing credentials and exact location."""
    if depth > 7:
        return "[limite de profundidade]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:300]:
            name = str(key)[:120]
            normalized = normalized_key(name)
            if any(token in normalized for token in (
                "password", "passwd", "token", "secret", "certificate", "privatekey", "authorization",
                "latitude", "longitude", "location", "coordinate", "vin", "deviceid", "userid", "email",
            )):
                result[name] = "[redigido]"
            else:
                result[name] = redacted_cloud_raw(item, depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [redacted_cloud_raw(item, depth + 1) for item in list(value)[:300]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = value if not isinstance(value, str) else value[:500]
        return text
    return redacted_cloud_raw(plain_data(value), depth + 1)


def object_scalar_map(data: Any) -> dict[str, Any]:
    result = scalar_map(plain_data(data))
    raw = attribute(data, "raw", None)
    for key, value in scalar_map(plain_data(raw)).items():
        result.setdefault(key, value)
    return result


def map_numeric(data: dict[str, Any], *aliases: str) -> float | None:
    return numeric(mapping_pick(data, tuple(aliases)))


def map_text(data: dict[str, Any], *aliases: str, max_length: int = 120) -> str | None:
    return text_value(mapping_pick(data, tuple(aliases)), max_length)


def normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def text_value(value: Any, max_length: int = 500) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = " ".join(str(value_of(value)).replace("\x00", " ").split())
    return text[:max_length] if text else None


def maintenance_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = text_value(value, 80)
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate).date().isoformat()
    except ValueError:
        pass
    for pattern in ("%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], pattern).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            return None
    match = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", text)
    if match:
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
        except ValueError:
            return None
    return None


def mapping_pick(data: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    indexed = {normalized_key(key): value for key, value in data.items()}
    for alias in aliases:
        key = normalized_key(alias)
        if key in indexed and indexed[key] not in (None, "", [], {}):
            return indexed[key]
    return None


def scalar_map(data: Any, depth: int = 0) -> dict[str, Any]:
    if depth > 6:
        return {}
    result: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            normalized = normalized_key(key)
            if not isinstance(value, (dict, list, tuple)) and normalized and normalized not in result:
                result[normalized] = value
            for child_key, child_value in scalar_map(value, depth + 1).items():
                result.setdefault(child_key, child_value)
    elif isinstance(data, (list, tuple)):
        for value in data[:100]:
            for child_key, child_value in scalar_map(value, depth + 1).items():
                result.setdefault(child_key, child_value)
    return result


def maintenance_item(data: dict[str, Any], kind: str, source: str) -> dict[str, Any] | None:
    title = text_value(mapping_pick(data, (
        "title", "name", "serviceName", "itemName", "maintenanceName", "maintainName",
        "projectName", "typeName", "maintenanceItem", "serviceItem",
    )), 160)
    description = text_value(mapping_pick(data, (
        "description", "details", "remark", "remarks", "content", "message", "serviceContent",
    )), 1000)
    history_date = maintenance_date(mapping_pick(data, (
        "serviceDate", "maintenanceDate", "maintainDate", "repairDate", "completedAt",
        "finishTime", "completedDate", "date", "time",
    )))
    due_date = maintenance_date(mapping_pick(data, (
        "dueDate", "nextDueDate", "nextMaintenanceDate", "nextServiceDate", "appointmentDate",
        "planDate", "scheduledDate", "nextMaintainDate", "date", "time",
    )))
    odometer = numeric(mapping_pick(data, (
        "odometerKm", "mileage", "serviceMileage", "maintenanceMileage", "maintainMileage", "currentMileage",
    )))
    due_odometer = numeric(mapping_pick(data, (
        "dueOdometerKm", "nextDueOdometerKm", "nextMaintenanceMileage", "nextServiceMileage",
        "nextMaintainMileage", "targetMileage", "mileage",
    )))
    provider = text_value(mapping_pick(data, (
        "provider", "dealerName", "serviceCenter", "shopName", "organization", "dealer",
    )), 160)
    status = text_value(mapping_pick(data, ("status", "state", "serviceStatus", "maintenanceStatus")), 40)
    service_date = history_date if kind == "history" else None
    next_date = due_date if kind == "upcoming" else None
    if not title:
        title = "Revisão realizada" if kind == "history" else "Próxima revisão"
    if not any((description, service_date, next_date, odometer, due_odometer, provider)):
        return None
    return {
        "kind": kind,
        "title": title,
        "description": description,
        "service_date": service_date,
        "due_date": next_date,
        "odometer_km": odometer if kind == "history" else None,
        "due_odometer_km": due_odometer if kind == "upcoming" else None,
        "provider": provider,
        "status": status or ("completed" if kind == "history" else "scheduled"),
        "source": source,
    }


HISTORY_CONTAINERS = {
    "maintenancehistory", "maintainhistory", "servicehistory", "maintenancerecords",
    "maintainrecords", "servicerecords", "repairrecords", "aftersalesrecords",
    "completedservices", "performedservices", "maintenancelist", "maintainlist",
}
UPCOMING_CONTAINERS = {
    "nextmaintenance", "nextservice", "maintenancereminder", "servicereminder",
    "upcomingmaintenance", "upcomingservice", "maintenanceplan", "serviceplan",
    "maintaininfo", "nextmaintaininfo", "maintenancedue",
}


def collect_container_items(data: Any, source: str, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 6:
        return []
    found: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            normalized = normalized_key(key)
            kind = "history" if normalized in HISTORY_CONTAINERS else ("upcoming" if normalized in UPCOMING_CONTAINERS else None)
            if kind:
                candidates = value if isinstance(value, list) else [value]
                for candidate in candidates[:100]:
                    if isinstance(candidate, dict):
                        item = maintenance_item(candidate, kind, source)
                        if item:
                            found.append(item)
            found.extend(collect_container_items(value, source, depth + 1))
    elif isinstance(data, list):
        for value in data[:100]:
            found.extend(collect_container_items(value, source, depth + 1))
    return found


def flat_maintenance_items(data: Any, source: str) -> list[dict[str, Any]]:
    flat = scalar_map(data)
    result: list[dict[str, Any]] = []
    upcoming = {
        "title": next((flat[key] for key in ("nextmaintenancename", "nextservicename", "maintainname") if key in flat), None),
        "description": next((flat[key] for key in ("nextmaintenancecontent", "nextservicecontent", "maintaincontent") if key in flat), None),
        "nextMaintenanceDate": next((flat[key] for key in ("nextmaintenancedate", "nextservicedate", "nextmaintaindate", "maintaindate") if key in flat), None),
        "nextMaintenanceMileage": next((flat[key] for key in ("nextmaintenancemileage", "nextservicemileage", "nextmaintainmileage", "maintainmileage") if key in flat), None),
        "provider": next((flat[key] for key in ("maintenancedealer", "servicedealer", "dealername") if key in flat), None),
    }
    if any(value not in (None, "") for value in upcoming.values()):
        item = maintenance_item(upcoming, "upcoming", source)
        if item:
            result.append(item)
    history = {
        "title": next((flat[key] for key in ("lastmaintenancename", "lastservicename") if key in flat), None),
        "description": next((flat[key] for key in ("lastmaintenancecontent", "lastservicecontent") if key in flat), None),
        "serviceDate": next((flat[key] for key in ("lastmaintenancedate", "lastservicedate", "lastmaintaindate") if key in flat), None),
        "serviceMileage": next((flat[key] for key in ("lastmaintenancemileage", "lastservicemileage", "lastmaintainmileage") if key in flat), None),
        "provider": next((flat[key] for key in ("lastmaintenancedealer", "lastservicedealer") if key in flat), None),
    }
    if any(value not in (None, "") for value in history.values()):
        item = maintenance_item(history, "history", source)
        if item:
            result.append(item)
    return result


def message_maintenance_items(messages: list[Any], vin: str, allow_unscoped: bool) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    keywords = re.compile(r"\b(maintenance|service|inspection|repair|recall|warranty)\b", re.IGNORECASE)
    completed = re.compile(r"\b(completed|performed|finished|serviced|repaired)\b", re.IGNORECASE)
    for message in messages[:100]:
        message_vin = str(attribute(message, "vin", "") or "").strip()
        if message_vin and vin and message_vin.upper() != vin.upper():
            continue
        if not message_vin and not allow_unscoped:
            continue
        title = text_value(attribute(message, "title"), 160) or "Aviso de manutenção Leap"
        body = text_value(attribute(message, "message"), 1000)
        combined = f"{title} {body or ''}"
        if not keywords.search(combined):
            continue
        kind = "history" if completed.search(combined) else "upcoming"
        item = maintenance_item({
            "title": title,
            "description": body,
            "serviceDate" if kind == "history" else "dueDate": maintenance_date(combined),
            "status": "completed" if kind == "history" else "notified",
        }, kind, "message")
        if item:
            result.append(item)
    return result


def serialize_maintenance(vehicle: Any, status: Any, messages: list[Any], allow_unscoped: bool) -> dict[str, Any]:
    vehicle_raw = attribute(vehicle, "raw", {})
    status_raw = attribute(status, "raw", {})
    history_and_upcoming = collect_container_items(vehicle_raw, "vehicle") + collect_container_items(status_raw, "status")
    for raw, source in ((vehicle_raw, "vehicle"), (status_raw, "status")):
        for item in flat_maintenance_items(raw, source):
            if not any(existing.get("kind") == item.get("kind") and existing.get("source") == source for existing in history_and_upcoming):
                history_and_upcoming.append(item)
    history_and_upcoming.extend(
        message_maintenance_items(messages, str(attribute(vehicle, "vin", "") or ""), allow_unscoped)
    )
    unique: dict[str, dict[str, Any]] = {}
    for item in history_and_upcoming:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=json_default)
        unique[key] = item
    items = list(unique.values())
    return {
        "history": [item for item in items if item.get("kind") == "history"],
        "upcoming": [item for item in items if item.get("kind") == "upcoming"],
        "synced_at": datetime.now().astimezone().isoformat(),
    }


def door_open(value: Any) -> bool | None:
    parsed = bool_or_none(value)
    return parsed


def window_open(value: Any) -> bool | None:
    if value is None:
        return None
    number = numeric(value)
    if number is not None:
        return number > 0
    return bool_or_none(value)


def first_bool(*values: Any) -> bool | None:
    """Return the first boolean signal that can be interpreted safely."""
    for value in values:
        parsed = bool_or_none(value)
        if parsed is not None:
            return parsed
    return None


def enum_or_value(value: Any) -> Any:
    """Serialize enums without losing unknown numeric signals."""
    if value is None:
        return None
    return value_of(value)


def compact_mapping(values: dict[str, Any]) -> dict[str, Any]:
    """Remove only unknown values; keep False and zero because they are real states."""
    return {key: value for key, value in values.items() if value is not None}


def build_visual_signature(
    primary_state: str,
    doors: dict[str, Any],
    windows: dict[str, Any],
    roof_open: bool | None,
    sunshade_open: bool | None,
    lights: dict[str, Any],
    security: dict[str, Any],
    climate: dict[str, Any],
    mirrors: dict[str, Any],
    charging: dict[str, Any],
) -> tuple[list[str], str]:
    """Build a deterministic state key used by the site asset resolver."""
    components: list[str] = []
    door_names = {
        "front_left": "front-left-open",
        "front_right": "front-right-open",
        "rear_left": "rear-left-open",
        "rear_right": "rear-right-open",
        "trunk": "trunk-open",
    }
    window_names = {
        "front_left": "window-front-left-open",
        "front_right": "window-front-right-open",
        "rear_left": "window-rear-left-open",
        "rear_right": "window-rear-right-open",
    }
    for key, component in door_names.items():
        if doors.get(key) is True:
            components.append(component)
    for key, component in window_names.items():
        if windows.get(key) is True:
            components.append(component)
    if roof_open is True:
        components.append("roof-open")
    if sunshade_open is True:
        components.append("sunshade-open")
    if lights.get("hazard") is True:
        components.append("hazard-on")
    elif any(value is True for value in lights.values()):
        components.append("lights-on")
    if security.get("sentry_mode") is True:
        components.append("sentry-on")
    if climate.get("on") is True:
        components.append("climate-on")
    if climate.get("battery_preheat") is True:
        components.append("battery-preheat-on")
    if mirrors.get("folded") is True:
        components.append("mirrors-folded")
    if charging.get("completed") is True:
        components.append("charge-completed")
    if primary_state != "parked":
        components.append(primary_state)
    components = sorted(set(components))
    signature_parts = [primary_state] + [item for item in components if item != primary_state]
    return components, "--".join(signature_parts)



def visual_component_states(
    primary_state: str,
    doors: dict[str, Any],
    windows: dict[str, Any],
    roof_open: bool | None,
    sunshade_open: bool | None,
    lights: dict[str, Any],
    security: dict[str, Any],
    climate: dict[str, Any],
    mirrors: dict[str, Any],
    charging: dict[str, Any],
) -> dict[str, bool | None]:
    """Publish explicit true/false/unknown states for the visual contract."""
    light_values = [value for value in lights.values() if isinstance(value, bool)]
    states: dict[str, bool | None] = {
        "front-left-open": doors.get("front_left"),
        "front-right-open": doors.get("front_right"),
        "rear-left-open": doors.get("rear_left"),
        "rear-right-open": doors.get("rear_right"),
        "trunk-open": doors.get("trunk"),
        "window-front-left-open": windows.get("front_left"),
        "window-front-right-open": windows.get("front_right"),
        "window-rear-left-open": windows.get("rear_left"),
        "window-rear-right-open": windows.get("rear_right"),
        "roof-open": roof_open,
        "sunshade-open": sunshade_open,
        "lights-on": any(light_values) if light_values else None,
        "hazard-on": lights.get("hazard"),
        "sentry-on": security.get("sentry_mode"),
        "climate-on": climate.get("on"),
        "battery-preheat-on": climate.get("battery_preheat"),
        "charge-completed": charging.get("completed"),
        "mirrors-folded": mirrors.get("folded"),
        "parked": primary_state == "parked",
        "unlocked": primary_state == "unlocked",
        "driving": primary_state == "driving",
        "plugged": primary_state == "plugged",
        "charging": primary_state == "charging",
    }
    return states


def visual_contract(component_states: dict[str, bool | None]) -> dict[str, Any]:
    known = sorted(key for key, value in component_states.items() if isinstance(value, bool))
    unknown = sorted(key for key, value in component_states.items() if value is None)
    active = sorted(key for key, value in component_states.items() if value is True)
    return {
        "schema": 1,
        "version": 6,
        "unknown_is_not_closed": True,
        "known_components": known,
        "unknown_components": unknown,
        "active_components": active,
    }


def visual_capabilities(
    doors: dict[str, Any],
    windows: dict[str, Any],
    roof_open: bool | None,
    sunshade_open: bool | None,
    lights: dict[str, Any],
    security: dict[str, Any],
    climate: dict[str, Any],
    mirrors: dict[str, Any],
    charging: dict[str, Any],
) -> dict[str, Any]:
    """Tell the site what was actually reported so unknown is not shown as closed."""
    return {
        "doors": sorted(key for key, value in doors.items() if value is not None),
        "windows": sorted(key for key, value in windows.items() if value is not None),
        "roof": roof_open is not None,
        "sunshade": sunshade_open is not None,
        "lights": sorted(key for key, value in lights.items() if value is not None),
        "security": sorted(key for key, value in security.items() if value is not None),
        "climate": sorted(key for key, value in climate.items() if value is not None),
        "mirrors": sorted(key for key, value in mirrors.items() if value is not None),
        "charging": sorted(key for key, value in charging.items() if value is not None),
    }


def visual_sensor_health(capabilities: dict[str, Any]) -> dict[str, Any]:
    """Summarize mapped visual signals without treating unsupported values as closed."""
    expected = {
        "doors": 5,
        "windows": 4,
        "roof": 1,
        "sunshade": 1,
        "lights": 5,
        "security": 3,
        "climate": 2,
        "mirrors": 3,
        "charging": 6,
    }
    groups: dict[str, dict[str, Any]] = {}
    known_total = 0
    expected_total = 0
    core_known = 0
    core_expected = 0
    for group, expected_count in expected.items():
        raw = capabilities.get(group)
        if isinstance(raw, list):
            known_count = len({str(item) for item in raw if str(item).strip()})
        elif isinstance(raw, bool):
            known_count = 1 if raw else 0
        else:
            known_count = 0
        known_count = max(0, min(expected_count, known_count))
        status = "complete" if known_count >= expected_count else ("partial" if known_count > 0 else "unavailable")
        groups[group] = {
            "known": known_count,
            "expected": expected_count,
            "status": status,
        }
        known_total += known_count
        expected_total += expected_count
        if group in {"doors", "windows", "roof", "sunshade"}:
            core_known += known_count
            core_expected += expected_count
    completeness = round((known_total / expected_total) * 100) if expected_total else 0
    core_completeness = round((core_known / core_expected) * 100) if core_expected else 0
    overall = "complete" if core_completeness >= 100 else ("partial" if known_total > 0 else "unavailable")
    return {
        "status": overall,
        "known": known_total,
        "expected": expected_total,
        "completeness_percent": completeness,
        "core_known": core_known,
        "core_expected": core_expected,
        "core_completeness_percent": core_completeness,
        "groups": groups,
    }


def visual_model_family(*values: Any) -> str | None:
    """Resolve only the public commercial family used by the visual catalog."""
    for value in values:
        text = str(value or "").strip().lower()
        normalized = "".join(char for char in text if char.isalnum())
        if "c10" in normalized:
            return "c10"
        if "b10" in normalized:
            return "b10"
    return None


def visual_fingerprint(payload: dict[str, Any]) -> str:
    """Create a stable fingerprint without VIN, credentials or account identifiers."""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_https_url(value: Any) -> str | None:
    text = text_value(value, 1000)
    if not text or not text.lower().startswith("https://"):
        return None
    return text


def charging_label(status: Any) -> str:
    charging = bool_or_none(attribute(status, "is_charging"))
    plugged = bool_or_none(attribute(status, "is_plugged"))
    parked = bool_or_none(attribute(status, "is_parked"))
    regenerating = bool_or_none(attribute(status, "is_regening"))
    battery = attribute(status, "battery")
    completed = bool_or_none(attribute(battery, "charge_completed"))
    state = value_of(attribute(battery, "charge_state"))
    state_text = str(state or "").lower()

    if regenerating is True or "regen" in state_text:
        return "regenerating"
    if charging is True:
        return "charging"
    if completed is True or "finish" in state_text or "complete" in state_text:
        return "completed"
    if charging is False:
        return "plugged" if plugged is True else "not_charging"
    if "charging" in state_text and parked is not False:
        return "charging"
    if plugged is True:
        return "plugged"
    return "not_charging"


def serialize_vehicle(vehicle: Any, include_status: bool, client: Any, messages: list[Any] | None = None, allow_unscoped_messages: bool = False) -> dict[str, Any]:
    vin = str(attribute(vehicle, "vin", "") or "").strip()
    remote_id = str(attribute(vehicle, "car_id", "") or vin).strip()
    model = str(attribute(vehicle, "car_type", "") or "Leapmotor").strip()
    nickname = str(attribute(vehicle, "vehicle_nickname", "") or attribute(vehicle, "user_nickname", "") or "").strip()
    plate = str(attribute(vehicle, "plate_number", "") or "").strip()
    display_name = nickname or (f"Leapmotor {model}" if model and model.lower() != "leapmotor" else "Meu Leapmotor")
    if plate and plate not in display_name:
        display_name = f"{display_name} · {plate}"

    raw_abilities = attribute(vehicle, "abilities", []) or []
    raw_rights = attribute(vehicle, "rights", []) or []
    raw_module_rights = attribute(vehicle, "module_rights", []) or []
    abilities = [str(value_of(item)) for item in raw_abilities]
    rights = [str(value_of(item)) for item in raw_rights]
    module_rights = [str(value_of(item)) for item in raw_module_rights]
    vehicle_scalars = object_scalar_map(vehicle)
    exterior_color = first_text(
        attribute(vehicle, "out_color"),
        map_text(vehicle_scalars, "outColor", "outsideColor", "exteriorColor", "bodyColor", "paintColor", "vehicleColor", "colorName"),
        max_length=80,
    )
    vehicle_image_url = safe_https_url(mapping_pick(vehicle_scalars, (
        "carPicture", "carPictureUrl", "carImage", "carImageUrl", "vehicleImage", "vehicleImageUrl",
        "outwardImage", "appearanceImage", "modelImage", "imageUrl",
    )))
    supported_commands = [
        key for key, method in COMMAND_METHODS.items()
        if callable(getattr(client, method, None))
    ]

    result: dict[str, Any] = {
        "remote_id": remote_id or vin,
        "vin": vin,
        "display_name": display_name[:120],
        "model": model[:80],
        "year": attribute(vehicle, "year"),
        "exterior_color": exterior_color,
        "vehicle_image_url": vehicle_image_url,
        "powertrain": None,
        "shared": bool(attribute(vehicle, "is_shared", False)),
        "capabilities": {
            "abilities": abilities,
            "rights": rights,
            "module_rights": module_rights,
            "supported_commands": supported_commands,
        },
    }
    if not include_status:
        return result

    status = client.get_vehicle_status(vehicle)
    result["maintenance"] = serialize_maintenance(vehicle, status, messages or [], allow_unscoped_messages)
    battery = attribute(status, "battery")
    driving = attribute(status, "driving")
    location = attribute(status, "location")
    climate = attribute(status, "climate")
    doors = attribute(status, "doors")
    windows = attribute(status, "windows")
    tires = attribute(status, "tires")
    connectivity = attribute(status, "connectivity")
    seat_comfort = attribute(status, "seat_comfort")
    security = attribute(status, "security")
    ignition = attribute(status, "ignition")

    tire_data = attribute(tires, "all_bar", {})
    if not isinstance(tire_data, dict):
        tire_data = {}

    speed_value = numeric(attribute(driving, "speed"))
    parked_value = bool_or_none(attribute(status, "is_parked")) if attribute(status, "is_parked") is not None else bool_or_none(attribute(driving, "is_parked"))
    ready_value = bool_or_none(attribute(driving, "ready")) if attribute(driving, "ready") is not None else bool_or_none(attribute(status, "ready"))
    ignition_value = bool_or_none(attribute(driving, "vehicle_on")) if attribute(driving, "vehicle_on") is not None else bool_or_none(attribute(status, "is_on"))
    charging_state = charging_label(status)
    plugged_value = bool_or_none(attribute(status, "is_plugged"))
    regenerating_value = bool_or_none(attribute(status, "is_regening"))
    explicit_charging_power = first_numeric(attribute(battery, "charging_power_kw"))
    battery_power = first_numeric(attribute(battery, "battery_power"))
    battery_current = first_numeric(
        attribute(battery, "charging_current"),
        attribute(battery, "charge_current"),
        attribute(battery, "battery_current"),
    )
    battery_voltage = first_numeric(
        attribute(battery, "charging_voltage"),
        attribute(battery, "charge_voltage"),
        attribute(battery, "battery_voltage"),
    )
    charging_power = explicit_charging_power if charging_state == "charging" else None
    if charging_state == "charging" and charging_power is None and battery_power is not None and battery_power < 0:
        charging_power = abs(battery_power)
    charging_current = abs(battery_current) if charging_state == "charging" and battery_current is not None else None
    charging_voltage = abs(battery_voltage) if charging_state == "charging" and battery_voltage is not None else None

    if charging_state == "charging":
        vehicle_state = "charging"
    elif regenerating_value is True or charging_state == "regenerating":
        vehicle_state = "regenerating"
    elif speed_value is not None and speed_value > 1:
        vehicle_state = "driving"
    elif ready_value is True or ignition_value is True:
        vehicle_state = "ready"
    elif parked_value is True:
        vehicle_state = "parked"
    else:
        vehicle_state = str(value_of(attribute(status, "vehicle_state")) or value_of(attribute(driving, "vehicle_state")) or "unknown")

    driving_scalars = object_scalar_map(driving)
    status_scalars = object_scalar_map(status)
    battery_scalars = object_scalar_map(battery)
    cloud_scalars = dict(status_scalars)
    for source_map in (driving_scalars, battery_scalars):
        for key, value in source_map.items():
            cloud_scalars.setdefault(key, value)

    door_state = {
        "front_left": door_open(attribute(doors, "lbcm_driver_door_status")),
        "front_right": door_open(attribute(doors, "rbcm_driver_door_status")),
        "rear_left": door_open(attribute(doors, "lbcm_left_rear_door_status")),
        "rear_right": door_open(attribute(doors, "rbcm_right_rear_door_status")),
        "trunk": door_open(attribute(doors, "bbcm_back_door_status")),
    }
    window_positions = {
        "front_left": first_numeric(attribute(windows, "left_front_window_percent")),
        "front_right": first_numeric(attribute(windows, "right_front_window_percent")),
        "rear_left": first_numeric(attribute(windows, "left_rear_window_percent")),
        "rear_right": first_numeric(attribute(windows, "right_rear_window_percent")),
    }
    window_state = {
        "front_left": window_open(window_positions["front_left"]) if window_positions["front_left"] is not None else first_bool(attribute(windows, "driver_window_status")),
        "front_right": window_open(window_positions["front_right"]) if window_positions["front_right"] is not None else first_bool(attribute(windows, "right_front_window_status")),
        "rear_left": window_open(window_positions["rear_left"]) if window_positions["rear_left"] is not None else first_bool(attribute(windows, "left_rear_window_status")),
        "rear_right": window_open(window_positions["rear_right"]) if window_positions["rear_right"] is not None else first_bool(attribute(windows, "right_rear_window_status")),
    }

    roof_opening = first_numeric(attribute(security, "roof_opening"), map_numeric(cloud_scalars, "roofOpening", "sunroofOpening", "roofOpenPercent"))
    sunshade_position = first_numeric(attribute(windows, "sun_shade"), map_numeric(cloud_scalars, "sunShade", "sunshadeOpening", "sunshadePercent"))
    roof_state = window_open(roof_opening) if roof_opening is not None else first_bool(map_text(cloud_scalars, "sunroofOpen", "roofOpen"))
    sunshade_state = window_open(sunshade_position) if sunshade_position is not None else first_bool(map_text(cloud_scalars, "sunshadeOpen"))

    lights_state = compact_mapping({
        "position": first_bool(mapping_pick(cloud_scalars, ("positionLamp", "positionLight", "parkingLight"))),
        "low_beam": first_bool(mapping_pick(cloud_scalars, ("lowBeam", "lowBeamLamp", "dippedBeam"))),
        "high_beam": first_bool(mapping_pick(cloud_scalars, ("highBeam", "highBeamLamp"))),
        "hazard": first_bool(mapping_pick(cloud_scalars, ("hazardLamp", "hazardLights", "doubleFlash"))),
        "daytime": first_bool(mapping_pick(cloud_scalars, ("daytimeRunningLamp", "daytimeLight", "drl"))),
    })
    mirrors_state = compact_mapping({
        "left_heating": first_bool(attribute(security, "left_mirror_heating"), mapping_pick(cloud_scalars, ("leftMirrorHeating",))),
        "right_heating": first_bool(attribute(security, "right_mirror_heating"), mapping_pick(cloud_scalars, ("rightMirrorHeating",))),
        "folded": first_bool(mapping_pick(cloud_scalars, ("rearviewMirrorFolded", "mirrorFolded", "mirrorsFolded"))),
    })
    security_state = compact_mapping({
        "active": first_bool(attribute(security, "is_security_active"), attribute(security, "vehicle_security_active")),
        "raw_state": enum_or_value(attribute(security, "vehicle_security_active")),
        "sentry_mode": first_bool(attribute(security, "sentry_mode")),
        "roof_open": roof_state,
        "roof_opening_percent": roof_opening,
        "sunshade_open": sunshade_state,
        "sunshade_percent": sunshade_position,
    })
    seat_state = compact_mapping({
        "driver_heating": first_numeric(attribute(seat_comfort, "driver_seat_heating")),
        "driver_ventilation": first_numeric(attribute(seat_comfort, "driver_seat_ventilation")),
        "passenger_heating": first_numeric(attribute(seat_comfort, "passenger_seat_heating")),
        "passenger_ventilation": first_numeric(attribute(seat_comfort, "passenger_seat_ventilation")),
        "steering_wheel_heating": first_numeric(attribute(seat_comfort, "steering_wheel_heating")),
        "steering_wheel_minutes": first_numeric(attribute(seat_comfort, "steering_wheel_heater_minutes")),
    })
    connectivity_state = compact_mapping({
        "bluetooth": first_bool(attribute(connectivity, "bluetooth_state")),
        "hotspot": first_bool(attribute(connectivity, "hotspot_state")),
    })
    climate_state = compact_mapping({
        "on": first_bool(attribute(climate, "ac_switch")),
        "left_temperature_c": first_numeric(attribute(climate, "ac_setting")),
        "right_temperature_c": first_numeric(attribute(climate, "ac_setting_right")),
        "fan_level": first_numeric(attribute(climate, "ac_air_volume"), attribute(climate, "ac_air_volume_setting")),
        "mode": enum_or_value(attribute(climate, "climate_mode")),
        "operate_mode": enum_or_value(attribute(climate, "ac_operate_mode")),
        "recirculation": enum_or_value(attribute(climate, "recirculation_mode")),
        "windshield_defrost": first_bool(attribute(climate, "is_windshield_defrost_active"), attribute(climate, "windshield_defrost")),
        "rear_window_heating": first_bool(attribute(climate, "rear_window_heating")),
        "rapid_cooling": first_bool(attribute(climate, "rapid_cooling")),
        "rapid_heating": first_bool(attribute(climate, "rapid_heating")),
        "battery_preheat": first_bool(
            attribute(climate, "battery_preheat"),
            attribute(climate, "battery_preheating"),
            mapping_pick(cloud_scalars, ("batteryPreheat", "batteryPreheating", "batteryHeating")),
        ),
    })
    charge_plan = attribute(battery, "charge_plan")
    charge_state_details = compact_mapping({
        "remaining_minutes": first_numeric(attribute(battery, "charge_remain_time")),
        "fast_connector": first_bool(attribute(battery, "is_charge_fast_gun_insert"), attribute(battery, "dc_input_fast_charge")),
        "slow_connector": first_bool(attribute(battery, "is_charge_slow_gun_insert"), attribute(battery, "ac_input_slow_charge")),
        "completed": first_bool(attribute(battery, "charge_completed")),
        "healthy_charge": first_bool(attribute(battery, "healthy_charge_enabled")),
        "thermal_request": enum_or_value(attribute(battery, "battery_thermal_request")),
        "schedule_enabled": first_bool(attribute(charge_plan, "enabled")),
        "schedule_start": text_value(attribute(charge_plan, "start"), 20),
        "schedule_end": text_value(attribute(charge_plan, "end"), 20),
        "schedule_cycles": text_value(attribute(charge_plan, "cycles"), 30),
    })

    visual_primary_state = "parked"
    if charging_state == "charging":
        visual_primary_state = "charging"
    elif plugged_value is True or charging_state in {"plugged", "completed"}:
        visual_primary_state = "plugged"
    elif speed_value is not None and speed_value > 1:
        visual_primary_state = "driving"
    elif bool_or_none(attribute(status, "is_locked")) is False:
        visual_primary_state = "unlocked"
    visual_components, visual_signature = build_visual_signature(
        visual_primary_state,
        door_state,
        window_state,
        roof_state,
        sunshade_state,
        lights_state,
        security_state,
        climate_state,
        mirrors_state,
        charge_state_details,
    )
    reported_visual_capabilities = visual_capabilities(
        door_state,
        window_state,
        roof_state,
        sunshade_state,
        lights_state,
        security_state,
        climate_state,
        mirrors_state,
        charge_state_details,
    )
    reported_visual_component_states = visual_component_states(
        visual_primary_state,
        door_state,
        window_state,
        roof_state,
        sunshade_state,
        lights_state,
        security_state,
        climate_state,
        mirrors_state,
        charge_state_details,
    )
    reported_visual_contract = visual_contract(reported_visual_component_states)
    captured_at = iso_timestamp(attribute(status, "collect_time") or attribute(status, "create_time"))
    model_code_candidate = first_text(
        map_text(vehicle_scalars, "modelCode", "carModel", "vehicleModel", "seriesCode"),
        model,
        max_length=80,
    )
    model_family_hint = visual_model_family(model, model_code_candidate)
    color_source = "vehicle.out_color" if attribute(vehicle, "out_color") is not None else ("vehicle.raw" if exterior_color else None)
    visual_identity = compact_mapping({
        "model": model[:80],
        "model_code": model_code_candidate,
        "model_family_hint": model_family_hint,
        "exterior_color": exterior_color,
        "image_url": vehicle_image_url,
        "model_source": "vehicle.car_type",
        "color_source": color_source,
    })
    visual_resolution_hints = {
        "schema": 1,
        "model": compact_mapping({
            "reported": model[:80],
            "code": model_code_candidate,
            "family_hint": model_family_hint,
            "source": "vehicle.car_type",
        }),
        "color": compact_mapping({
            "reported": exterior_color,
            "source": color_source,
        }),
        "asset": compact_mapping({
            "cloud_image_available": bool(vehicle_image_url),
            "cloud_image_https": bool(vehicle_image_url and str(vehicle_image_url).lower().startswith("https://")),
        }),
    }
    visual_diagnostics = visual_sensor_health(reported_visual_capabilities)
    identity_warnings: list[str] = []
    if model_family_hint is None:
        identity_warnings.append("model_family_not_recognized")
    if not exterior_color:
        identity_warnings.append("exterior_color_not_reported")
    if int(visual_diagnostics.get("core_known") or 0) <= 0:
        identity_warnings.append("core_visual_sensors_unavailable")
    visual_diagnostics["identity"] = {
        "model_present": bool(model),
        "model_family_recognized": model_family_hint is not None,
        "color_present": bool(exterior_color),
        "cloud_image_present": bool(vehicle_image_url),
    }
    visual_diagnostics["warnings"] = identity_warnings
    visual_diagnostics["missing_groups"] = [
        name for name, group in (visual_diagnostics.get("groups") or {}).items()
        if isinstance(group, dict) and str(group.get("status") or "") != "complete"
    ]
    visual_fingerprint_value = visual_fingerprint({
        "version": 6,
        "identity": visual_identity,
        "resolution_hints": visual_resolution_hints,
        "primary": visual_primary_state,
        "signature": visual_signature,
        "components": visual_components,
        "component_states": reported_visual_component_states,
        "contract": reported_visual_contract,
        "doors": compact_mapping(door_state),
        "windows": compact_mapping(window_state),
        "window_positions": compact_mapping(window_positions),
        "roof": compact_mapping({"open": roof_state, "percent": roof_opening}),
        "sunshade": compact_mapping({"open": sunshade_state, "percent": sunshade_position}),
        "lights": lights_state,
        "mirrors": mirrors_state,
        "security": security_state,
        "climate": climate_state,
        "charging": charge_state_details,
    })
    visual_sample_fingerprint = visual_fingerprint({
        "state": visual_fingerprint_value,
        "captured_at": captured_at,
    })

    tire_states = compact_mapping({
        "front_left": enum_or_value(attribute(tires, "front_left_state")),
        "front_right": enum_or_value(attribute(tires, "front_right_state")),
        "rear_left": enum_or_value(attribute(tires, "rear_left_state")),
        "rear_right": enum_or_value(attribute(tires, "rear_right_state")),
        "all_ok": first_bool(attribute(tires, "all_ok")),
    })
    ignition_state = compact_mapping({
        "on1": first_bool(attribute(ignition, "bcm_key_position_on1")),
        "on2": first_bool(attribute(ignition, "bcm_key_position_on2")),
        "on3": first_bool(attribute(ignition, "bcm_key_position_on3")),
    })

    official_total = first_numeric(
        map_numeric(driving_scalars, "officialTripEnergyKwh", "officialTripEnergy", "tripEnergyKwh", "tripEnergy", "currentTripEnergy", "energyConsumption"),
        attribute(driving, "trip_energy_kwh"), attribute(driving, "current_trip_energy"), attribute(driving, "energy_consumption"),
    )
    official_driving = map_numeric(cloud_scalars, "officialTripDrivingKwh", "tripDrivingEnergyKwh", "drivingEnergyKwh", "driveEnergyKwh", "drivingConsumptionKwh")
    official_climate = map_numeric(cloud_scalars, "officialTripClimateKwh", "tripClimateEnergyKwh", "climateEnergyKwh", "airConditionEnergyKwh", "acEnergyKwh")
    official_other = map_numeric(cloud_scalars, "officialTripOtherKwh", "tripOtherEnergyKwh", "otherEnergyKwh", "auxiliaryEnergyKwh")
    if official_total is None and any(value is not None for value in (official_driving, official_climate, official_other)):
        official_total = round(sum(value or 0.0 for value in (official_driving, official_climate, official_other)), 3)

    unread_messages = 0
    for message in messages or []:
        read_flag = attribute(message, "read")
        if read_flag is None:
            read_flag = attribute(message, "is_read")
        if read_flag is False or str(value_of(read_flag)).lower() in {"0", "false", "unread"}:
            unread_messages += 1

    telemetry: dict[str, Any] = {
        "soc": numeric(attribute(battery, "precise_soc")) or numeric(attribute(battery, "soc")),
        "estimated_range_km": numeric(attribute(battery, "expected_mileage")) or numeric(attribute(driving, "live_remaining_range")),
        "odometer_km": numeric(attribute(driving, "total_mileage")),
        "speed_kmh": speed_value,
        "is_parked": parked_value,
        "vehicle_state": vehicle_state,
        "gear_position": value_of(attribute(driving, "gear_position")) or value_of(attribute(driving, "gear")) or value_of(attribute(status, "gear_position")),
        "parking_brake": bool_or_none(attribute(driving, "parking_brake")) if attribute(driving, "parking_brake") is not None else bool_or_none(attribute(status, "parking_brake")),
        "ignition_on": ignition_value,
        "ready_state": ready_value,
        "charging_status": charging_state,
        "charging_power_kw": charging_power,
        "charging_current_a": charging_current,
        "charging_voltage_v": charging_voltage,
        "locked": bool_or_none(attribute(status, "is_locked")),
        "plugged": plugged_value,
        "climate_on": bool_or_none(attribute(climate, "ac_switch")),
        "target_cabin_temp_c": numeric(attribute(climate, "target_temperature")) or numeric(attribute(climate, "setting_temperature")) or numeric(attribute(climate, "set_temp")),
        "charge_limit_percent": numeric(attribute(battery, "charge_limit")) or numeric(attribute(battery, "target_soc")) or numeric(attribute(battery, "charging_limit")),
        "battery_temp_c": numeric(attribute(battery, "min_battery_temp")),
        "cabin_temp_c": numeric(attribute(climate, "interior_temp")),
        "outside_temp_c": numeric(attribute(climate, "outdoor_temp")),
        "fuel_level_percent": first_numeric(
            attribute(driving, "fuel_level_percent"), attribute(driving, "fuel_percent"),
            attribute(driving, "tank_level_percent"), attribute(driving, "fuel_soc"),
            attribute(status, "fuel_level_percent"), attribute(status, "fuel_percent"),
        ),
        "fuel_range_km": first_numeric(
            attribute(driving, "fuel_remaining_range"), attribute(driving, "fuel_range"),
            attribute(driving, "fuel_mileage"), attribute(driving, "range_extender_range"),
            attribute(status, "fuel_range_km"), attribute(status, "fuel_range"),
        ),
        "combined_range_km": first_numeric(
            attribute(driving, "combined_remaining_range"), attribute(driving, "total_remaining_range"),
            attribute(driving, "comprehensive_range"), attribute(status, "combined_range_km"),
            attribute(status, "total_range_km"),
        ),
        "fuel_consumption_l_100km": first_numeric(
            attribute(driving, "fuel_consumption_l_100km"), attribute(driving, "fuel_consumption"),
            attribute(driving, "average_fuel_consumption"), attribute(driving, "avg_fuel_consumption"),
            attribute(status, "fuel_consumption_l_100km"),
        ),
        "engine_running": bool_or_none(first_text(
            attribute(driving, "engine_running"), attribute(driving, "generator_running"),
            attribute(driving, "range_extender_running"), attribute(status, "engine_running"),
            attribute(status, "generator_running"),
        )),
        "generator_status": first_text(
            attribute(driving, "generator_status"), attribute(driving, "range_extender_status"),
            attribute(driving, "engine_status"), attribute(status, "generator_status"),
            attribute(status, "range_extender_status"),
        ),
        "reev_energy_mode": first_text(
            attribute(driving, "energy_mode"), attribute(driving, "power_mode"),
            attribute(driving, "range_extender_mode"), attribute(status, "energy_mode"),
            attribute(status, "power_mode"),
        ),
        "software_version": value_of(attribute(status, "software_version")) or value_of(attribute(status, "ota_version")) or value_of(attribute(vehicle, "software_version")),
        "ota_update_available": bool_or_none(attribute(status, "ota_update_available")) if attribute(status, "ota_update_available") is not None else bool_or_none(attribute(status, "update_available")),
        "unread_messages": unread_messages,
        "data_source": "leapmotor-cloud",
        "official_trip_energy_kwh": official_total,
        "official_trip_reference": map_text(cloud_scalars, "officialTripReference", "officialTripId", "tripRecordId", "journeyId", "travelId", "tripId"),
        "official_trip_started_at": optional_timestamp(mapping_pick(cloud_scalars, ("officialTripStartedAt", "tripStartTime", "journeyStartTime", "travelStartTime", "startTime"))),
        "official_trip_ended_at": optional_timestamp(mapping_pick(cloud_scalars, ("officialTripEndedAt", "tripEndTime", "journeyEndTime", "travelEndTime", "endTime"))),
        "official_trip_distance_km": map_numeric(cloud_scalars, "officialTripDistanceKm", "tripDistanceKm", "journeyDistanceKm", "travelDistanceKm", "tripMileage"),
        "official_trip_driving_kwh": official_driving,
        "official_trip_climate_kwh": official_climate,
        "official_trip_other_kwh": official_other,
        "official_trip_status": map_text(cloud_scalars, "officialTripStatus", "tripAggregationStatus", "tripStatus", "journeyStatus", max_length=30),
        "official_cumulative_trip_count": map_numeric(cloud_scalars, "officialCumulativeTripCount", "cumulativeTripCount", "totalTripCount", "travelCount"),
        "official_cumulative_distance_km": map_numeric(cloud_scalars, "officialCumulativeDistanceKm", "cumulativeDistanceKm", "totalTripDistanceKm", "totalTravelDistanceKm"),
        "official_cumulative_energy_kwh": map_numeric(cloud_scalars, "officialCumulativeEnergyKwh", "cumulativeEnergyKwh", "totalTripEnergyKwh", "totalTravelEnergyKwh"),
        "official_cumulative_driving_kwh": map_numeric(cloud_scalars, "officialCumulativeDrivingKwh", "cumulativeDrivingEnergyKwh", "totalDrivingEnergyKwh"),
        "official_cumulative_climate_kwh": map_numeric(cloud_scalars, "officialCumulativeClimateKwh", "cumulativeClimateEnergyKwh", "totalClimateEnergyKwh"),
        "official_cumulative_other_kwh": map_numeric(cloud_scalars, "officialCumulativeOtherKwh", "cumulativeOtherEnergyKwh", "totalOtherEnergyKwh"),
        "official_cumulative_updated_at": optional_timestamp(mapping_pick(cloud_scalars, ("officialCumulativeUpdatedAt", "cumulativeUpdatedAt", "statisticsUpdatedAt", "dataUpdatedAt"))),
        "regenerated_energy_kwh": first_numeric(attribute(driving, "regenerated_energy_kwh"), attribute(driving, "recovery_energy"), map_numeric(cloud_scalars, "regeneratedEnergyKwh", "recoveryEnergyKwh")),
        "latitude": numeric(attribute(location, "latitude")),
        "longitude": numeric(attribute(location, "longitude")),
        "doors": door_state,
        "windows": window_state,
        "window_positions": compact_mapping(window_positions),
        "roof_open": roof_state,
        "roof_open_percent": roof_opening,
        "sunshade_open": sunshade_state,
        "sunshade_percent": sunshade_position,
        "lights": lights_state,
        "mirrors": mirrors_state,
        "security": security_state,
        "seat_comfort": seat_state,
        "connectivity": connectivity_state,
        "climate_details": climate_state,
        "charging_details": charge_state_details,
        "tire_status": tire_states,
        "ignition_details": ignition_state,
        "vehicle_image_url": vehicle_image_url,
        "exterior_color": exterior_color,
        "visual_state_version": 6,
        "visual_primary_state": visual_primary_state,
        "visual_components": visual_components,
        "visual_component_states": reported_visual_component_states,
        "visual_contract": reported_visual_contract,
        "visual_signature": visual_signature,
        "visual_fingerprint": visual_fingerprint_value,
        "visual_sample_fingerprint": visual_sample_fingerprint,
        "visual_identity": visual_identity,
        "visual_resolution_hints": visual_resolution_hints,
        "visual_capabilities": reported_visual_capabilities,
        "visual_diagnostics": visual_diagnostics,
        "visual_state": {
            "version": 6,
            "captured_at": captured_at,
            "fingerprint": visual_fingerprint_value,
            "sample_fingerprint": visual_sample_fingerprint,
            "identity": visual_identity,
            "resolution_hints": visual_resolution_hints,
            "primary": visual_primary_state,
            "signature": visual_signature,
            "components": visual_components,
            "component_states": reported_visual_component_states,
            "contract": reported_visual_contract,
            "capabilities": reported_visual_capabilities,
            "diagnostics": visual_diagnostics,
            "doors": door_state,
            "windows": window_state,
            "window_positions": compact_mapping(window_positions),
            "roof": compact_mapping({"open": roof_state, "percent": roof_opening}),
            "sunshade": compact_mapping({"open": sunshade_state, "percent": sunshade_position}),
            "lights": lights_state,
            "mirrors": mirrors_state,
            "security": security_state,
            "climate": climate_state,
            "charging": charge_state_details,
        },
        "tire_data": {key: numeric(value) for key, value in tire_data.items()},
        "captured_at": captured_at,
        "cloud_raw_redacted": redacted_cloud_raw({
            "vehicle": attribute(vehicle, "raw", {}),
            "status": attribute(status, "raw", {}),
        }),
        "mapping_version": "1.11.62",
    }
    result["telemetry"] = telemetry
    return result


def create_client(credentials: dict[str, Any], temp_dir: Path, operation_password: str | None = None) -> Any:
    try:
        from leapmotor_api import LeapmotorApiClient
    except ImportError as exc:
        raise RuntimeError("A biblioteca leapmotor-api não está instalada no ambiente Python.") from exc

    email = require_text(credentials, "email", "o e-mail da conta Leapmotor", 190)
    password = require_text(credentials, "password", "a senha da conta Leapmotor", 500)
    certificate = validate_pem(
        require_text(credentials, "certificate_pem", "o certificado do aplicativo", 160 * 1024),
        ("CERTIFICATE",),
        "certificado",
    )
    private_key = validate_pem(
        require_text(credentials, "private_key_pem", "a chave privada do aplicativo", 160 * 1024),
        ("PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY"),
        "chave privada",
    )

    cert_path = temp_dir / "app_cert.pem"
    key_path = temp_dir / "app_key.pem"
    write_secret(cert_path, certificate)
    write_secret(key_path, private_key)

    # O endpoint internacional da própria Leapmotor apresenta uma cadeia TLS
    # autoassinada. A biblioteca oficial da comunidade já trata esse endpoint
    # com verify_ssl=False por padrão. Mantemos a exceção somente para o host
    # fixo embutido na biblioteca; não existe URL configurável pelo usuário.
    # Operadores podem forçar validação pública estrita para diagnóstico.
    strict_tls = os.environ.get("LEAPHUB_LEAPMOTOR_STRICT_TLS", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }

    return LeapmotorApiClient(
        username=email,
        password=password,
        app_cert_path=cert_path,
        app_key_path=key_path,
        operation_password=operation_password,
        timeout=35,
        verify_ssl=strict_tls,
        language="en-GB",
    )


def handle_account(payload: dict[str, Any], sync: bool) -> dict[str, Any]:
    credentials_value = payload.get("credentials") if sync else payload
    credentials = credentials_value if isinstance(credentials_value, dict) else {}
    vehicle_id = str(payload.get("vehicle_id") or "").strip() if sync else ""
    temp_dir = secure_temp_directory()
    client = None
    try:
        client = create_client(credentials, temp_dir, None)
        client.login()
        vehicles = client.get_vehicle_list()
        if not isinstance(vehicles, list):
            vehicles = list(vehicles or [])
        selected = vehicles
        if vehicle_id:
            selected = [
                item
                for item in vehicles
                if str(attribute(item, "car_id", "") or attribute(item, "vin", "")) == vehicle_id
            ]
            if not selected and len(vehicles) == 1:
                selected = vehicles
        messages: list[Any] = []
        get_messages = getattr(client, "get_message_list", None)
        if callable(get_messages):
            try:
                message_page = get_messages(page_no=1, page_size=100)
                messages = list(attribute(message_page, "messages", []) or [])
            except Exception:
                messages = []
        serialized = [
            serialize_vehicle(
                item,
                include_status=True,
                client=client,
                messages=messages,
                allow_unscoped_messages=len(selected) == 1,
            )
            for item in selected
        ]
        if not serialized:
            raise RuntimeError("Nenhum veículo foi encontrado para esta conta.")
        return {
            "ok": True,
            "account_name": "Conta Leapmotor",
            "vehicles": serialized,
            "connector_version": CONNECTOR_VERSION,
            "library_version": package_version(),
        }
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)


def handle_command(payload: dict[str, Any]) -> dict[str, Any]:
    credentials = payload.get("credentials")
    if not isinstance(credentials, dict):
        raise ValueError("Credenciais do comando ausentes.")
    vehicle_id = require_text(payload, "vehicle_id", "o identificador do veículo", 190)
    command = require_text(payload, "command", "o comando remoto", 80)
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {}
    if command not in COMMAND_METHODS:
        raise ValueError("Comando remoto não suportado pelo conector.")
    operation_password = require_text(credentials, "operation_password", "o PIN do veículo", 20)

    temp_dir = secure_temp_directory()
    client = None
    try:
        client = create_client(credentials, temp_dir, operation_password)
        client.login()
        method_name = COMMAND_METHODS[command]
        method = getattr(client, method_name, None)
        if not callable(method):
            raise RuntimeError("A versão instalada da biblioteca não possui este comando.")

        if command == "set_charge_limit":
            value = int(parameters.get("charge_limit_percent", 80))
            if value < 50 or value > 100 or value % 5 != 0:
                raise ValueError("Limite de carga inválido.")
            result = method(vehicle_id, charge_limit_percent=value)
        elif command == "send_destination":
            name = str(parameters.get("name") or "Destino")[:100]
            address = str(parameters.get("address") or "")[:240]
            latitude = float(parameters.get("latitude"))
            longitude = float(parameters.get("longitude"))
            if latitude < -90 or latitude > 90 or longitude < -180 or longitude > 180:
                raise ValueError("Coordenadas inválidas.")
            result = method(vehicle_id, name=name, address=address, latitude=latitude, longitude=longitude)
        else:
            result = method(vehicle_id)

        return {
            "ok": True,
            "message": "Comando enviado à nuvem Leapmotor.",
            "command": command,
            "result_type": type(result).__name__,
            "connector_version": CONNECTOR_VERSION,
            "library_version": package_version(),
        }
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> None:
    request = read_request()
    action = str(request.get("action") or (sys.argv[1] if len(sys.argv) > 1 else "health"))
    payload = request.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    library = package_version()
    if action == "health":
        if library is None:
            emit(
                {
                    "ok": False,
                    "message": "A biblioteca leapmotor-api ainda não está instalada.",
                    "connector_version": CONNECTOR_VERSION,
                    "library_version": None,
                    "python_version": sys.version.split()[0],
                },
                2,
            )
        emit(
            {
                "ok": True,
                "message": "Conector Python local pronto para telemetria e comandos remotos protegidos.",
                "connector_version": CONNECTOR_VERSION,
                "library_version": library,
                "python_version": sys.version.split()[0],
            }
        )
    if action == "test_account":
        emit(handle_account(payload, sync=False))
    if action == "sync":
        emit(handle_account(payload, sync=True))
    if action == "command":
        emit(handle_command(payload))
    raise ValueError("Ação não suportada pelo conector.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as exc:
        emit({"ok": False, "message": clean_message(str(exc)), "connector_version": CONNECTOR_VERSION}, 2)
    except Exception as exc:
        emit(
            {
                "ok": False,
                "message": "Falha interna no conector: " + clean_message(str(exc)),
                "connector_version": CONNECTOR_VERSION,
            },
            3,
        )
