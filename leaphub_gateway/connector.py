#!/usr/bin/env python3
"""Leap Hub local connector for telemetry and safeguarded remote commands.

Reads a single JSON request from stdin and writes a single JSON response to stdout.
Credentials never appear in command-line arguments or environment variables.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import inspect
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

try:
    from leaphub_privacy import sanitize_log
except ImportError:
    try:
        from privacy import sanitize_log
    except ImportError:
        import importlib.util as _importlib_util
        _privacy_spec = _importlib_util.spec_from_file_location("leaphub_privacy_local", Path(__file__).with_name("privacy.py"))
        if _privacy_spec is None or _privacy_spec.loader is None:
            raise
        _privacy_module = _importlib_util.module_from_spec(_privacy_spec)
        _privacy_spec.loader.exec_module(_privacy_module)
        sanitize_log = _privacy_module.sanitize_log

CONNECTOR_VERSION = "1.12.107"
MAX_INPUT_BYTES = 1024 * 1024
logging.getLogger("leapmotor_api").setLevel(logging.WARNING)
LOGGER = logging.getLogger("leaphub.connector")


def connector_log(level: int, message: str, *args: Any) -> None:
    """Best-effort logging that can never interrupt a vehicle command."""
    try:
        LOGGER.log(level, message, *args)
    except Exception:
        pass


CLIMATE_VERIFY_COMMANDS = {"climate_on", "climate_off", "quick_cool", "quick_heat"}
SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}
# 1.12.80 — estes comandos retornam ao Gateway assim que a escrita remota foi
# aceita. A própria leapmotor-api 0.3.2 faz polling síncrono do remoteCtlId;
# aqui isso é redundante porque a confirmação física já é feita pela telemetria
# FAST do Gateway. Na 1.12.81 climate_off entra na mesma estratégia,
# preservando o ac_switch operate=off e o teto de duas transmissões exatas.
# 1.12.84 — porta-malas, janelas e cortina também são comandos de ESTADO
# confirmáveis pela telemetria. Eles deixam de esperar o polling síncrono do
# remoteCtlId, mas continuam sem qualquer retry físico adicional.
ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windows_open", "windows_close", "sunshade_open", "sunshade_close"}

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
    # 1.12.69 — cortina numa posição intermediária, no mesmo cmd 161 e direito
    # 161 dos dois acima. A ESCALA NÃO É A MESMA DAS JANELAS: a biblioteca
    # documenta a cortina em 0-10 (`SunshadeValue.OPEN = "10"`), enquanto a
    # telemetria do C10/B10 publica a abertura dela em 0-100. O gateway recebe
    # 0-100 — que é o que o site mostra e o que o dono lê na tela — e converte.
    # Ver o tratamento em execute_vehicle_command.
    "sunshade_position": "control_sunshade",
    "climate_on": "ac_on",
    "climate_off": "ac_switch",
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
    "steering_wheel_heat_on": "steering_wheel_heat_on",
    "steering_wheel_heat_off": "steering_wheel_heat_off",
    "rearview_mirror_heat_on": "rearview_mirror_heat_on",
    "rearview_mirror_heat_off": "rearview_mirror_heat_off",
    # Comandos gateados pela capacidade do veículo (ver COMMAND_REQUIRED_RIGHT).
    # Cada um só é anunciado para o carro que possui o direito correspondente.
    "hotspot": "hotspot",
    "fuel_heating_on": "fuel_heating_on",
    "fuel_heating_off": "fuel_heating_off",
    "healthy_charging_on": "healthy_charging_on",
    "healthy_charging_off": "healthy_charging_off",
    "ble_key_restart": "ble_key_restart",
    # Conforto de assento: recebem posição (1-6) e nível (0-3) em `parameters`.
    # Ver SEAT_COMFORT_COMMANDS e o tratamento em execute_vehicle_command.
    "seat_heat": "seat_heat",
    "seat_ventilation": "seat_ventilation",
    # Teto solar (direito 160). Não confundir com a cortina do teto
    # (sunshade_open/close, direito 161), que é outro direito e já está acima.
    "sunroof_open": "open_sunroof",
    "sunroof_close": "close_sunroof",
    # Janela numa posição intermediária, 0 a 100. windows_open/windows_close são
    # o mesmo comando 230 nos extremos e continuam existindo.
    "windows_position": "windows",
    # Limite de velocidade em km/h.
    "set_speed_limit": "set_speed_limit",
    # Mídia: `operation` em play/pause/next/previous.
    "music": "music",
    "video": "video",
}

# Comandos que exigem posição e nível de assento. Mantidos em conjunto próprio
# porque são os primeiros da matriz estável que não são de argumento zero.
# Posições, conforme a biblioteca: 1=dianteiro esquerdo, 2=passageiro,
# 3=motorista, 4=dianteiro direito, 5=traseiro esquerdo, 6=traseiro direito.
SEAT_COMFORT_COMMANDS = frozenset({"seat_heat", "seat_ventilation"})

# Comandos de mídia, que compartilham o mesmo vocabulário de operação.
MEDIA_COMMANDS = frozenset({"music", "video"})
MEDIA_OPERATIONS = frozenset({"play", "pause", "next", "previous"})

# Recursos deliberadamente fora da matriz estável. Eles só são aceitos quando
# o site envia confirmação experimental explícita para um proprietário
# previamente autorizado. Não anunciar aqui evita que clientes antigos os
# tratem como comandos gerais.
EXPERIMENTAL_COMMAND_METHODS: dict[str, str] = {
    "sentry_on": "sentry_mode_on",
    "sentry_off": "sentry_mode_off",
    # A nuvem aceita um JSON livre em prepare_car (360) e a forma do pacote do
    # comando imediato não é documentada — só a do agendamento (361). O envelope
    # montado aqui é allow-listed e validado, mas segue exigindo confirmação
    # explícita do proprietário até haver captura de tráfego real.
    "prepare_car": "prepare_car",
    # 1.12.59 — o restante da superfície da biblioteca. Cada um destes fica
    # fechado até um administrador liberar o recurso para um proprietário
    # específico, do mesmo modo que o Sentinela, e ainda exige a confirmação
    # explícita de quem aciona. O motivo de cada um estar aqui e não na matriz
    # estável está em RELEASE-1.12.64.md.
    "autopark": "autopark",
    "piloted_parking": "piloted_parking",
    "on3_on": "on3_on",
    "on3_off": "on3_off",
    "seat_adjust": "seat_adjust",
    "rear_seats": "rear_seats",
    "fota_download": "fota_download",
    "fota_install": "fota_install",
    "fota_schedule": "fota_schedule",
}

# Comandos que podem pôr o carro em movimento sozinho. Além do gate experimental
# e da liberação por proprietário, exigem um reconhecimento próprio: quem aciona
# precisa declarar que está junto do carro e com ele à vista. O aplicativo não
# tem como provar isso — o que ele pode fazer é não deixar acontecer por
# distração, e registrar que foi declarado.
VEHICLE_MOTION_COMMANDS = frozenset({"autopark", "piloted_parking"})

# Comandos cuja forma de pacote a biblioteca declara apenas como "the full JSON
# payload string": não há vocabulário documentado para validar por campo. Em vez
# de repassar o que vier, o gateway confere a *forma* (objeto raso, chaves com
# nome plausível, valores escalares, tetos de quantidade e tamanho) e recusa o
# resto. Ver raw_command_payload().
RAW_PAYLOAD_COMMANDS = frozenset({"seat_adjust", "piloted_parking"})
# Só o Sentinela tem diagnóstico próprio (sonda, evidência e resumo do resultado).
# Este conjunto era derivado de EXPERIMENTAL_COMMAND_METHODS; deixou de ser quando
# um segundo experimental entrou, para que prepare_car não passe a ser tratado como
# sonda do Sentinela nem carregue os campos de diagnóstico dele.
SENTRY_COMMANDS = frozenset({"sentry_on", "sentry_off"})
ALL_COMMAND_METHODS: dict[str, str] = {**COMMAND_METHODS, **EXPERIMENTAL_COMMAND_METHODS}

# Direito (VehicleRight) exigido por cada comando. Serve para filtrar a matriz
# conforme a capacidade real de cada veículo (um C10 REEV expõe fuel_heating; um
# C10 BEV não). Códigos idênticos aos de leapmotor_api.mappings.REMOTE_ACTION_SPECS.
COMMAND_REQUIRED_RIGHT: dict[str, int] = {
    "lock": 110, "unlock": 110,
    "find_car": 120,
    "trunk_open": 130, "trunk_close": 130,
    "windows_open": 230, "windows_close": 230,
    "sunshade_open": 161, "sunshade_close": 161, "sunshade_position": 161,
    "climate_on": 170, "climate_off": 170,
    "quick_cool": 171, "quick_heat": 171,
    "windshield_defrost": 460,
    "battery_preheat_on": 190, "battery_preheat_off": 190,
    "start_charging": 193, "stop_charging": 193,
    "unlock_charger": 192,
    "set_charge_limit": 340,
    "send_destination": 180,
    "steering_wheel_heat_on": 320, "steering_wheel_heat_off": 320,
    "rearview_mirror_heat_on": 440, "rearview_mirror_heat_off": 440,
    "hotspot": 140,
    "fuel_heating_on": 380, "fuel_heating_off": 380,
    "healthy_charging_on": 480, "healthy_charging_off": 480,
    "ble_key_restart": 430,
    "seat_heat": 301,
    "seat_ventilation": 370,
    "sunroof_open": 160, "sunroof_close": 160,
    "windows_position": 230,
    "set_speed_limit": 510,
    "music": 270,
    "video": 290,
    # experimentais
    "sentry_on": 220, "sentry_off": 220,
    "prepare_car": 360,
    "autopark": 150,
    "piloted_parking": 350,
    # ON3 tem código de direito próprio (VehicleRight.ON3 = 410), ao contrário do
    # que se poderia supor por não ter descrição funcional.
    "on3_on": 410, "on3_off": 410,
    "seat_adjust": 280,
    "rear_seats": 470,
    "fota_download": 390,
    "fota_install": 391,
    # O agendamento tem direito próprio, separado do da instalação.
    "fota_schedule": 392,
}

# Flags de hardware (VehicleAbility) -> direitos que elas implicam, para quando a
# nuvem devolve `abilities` em vez de (ou além de) `rights`. Fonte: a tabela
# ABILITY_TO_RIGHTS de leapmotor_api.mappings.
ABILITY_TO_RIGHTS: dict[int, tuple[int, ...]] = {
    1: (110,), 2: (120,), 3: (130,), 4: (150,), 6: (170,), 9: (171,),
    10: (190,), 11: (161,), 12: (230,), 14: (301,), 15: (320,), 17: (171,),
    18: (460,), 24: (130,), 25: (160,), 30: (180,), 34: (510,), 35: (340,),
    36: (230,), 38: (360, 361), 40: (380,), 42: (370,), 43: (370,), 48: (192,),
    50: (220,), 52: (180,),
}


def _capability_code(item: Any) -> int | None:
    """Extrai o código numérico de um item de rights/abilities (IntEnum, int,
    dict com code/value/... ou string começada por dígitos)."""
    try:
        return int(item)
    except (TypeError, ValueError):
        pass
    raw = value_of(item)
    try:
        return int(raw)
    except (TypeError, ValueError):
        pass
    for key in ("code", "value", "id", "right", "ability"):
        candidate = attribute(item, key)
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    match = re.match(r"\s*(\d+)", str(raw if raw is not None else item))
    return int(match.group(1)) if match else None


def effective_right_codes(raw_rights: Any, raw_abilities: Any) -> set[int]:
    """Conjunto de direitos efetivos do veículo: os `rights` declarados mais os
    direitos implicados pelas `abilities` de hardware."""
    codes: set[int] = set()
    for item in (raw_rights or []):
        code = _capability_code(item)
        if code is not None:
            codes.add(code)
    for item in (raw_abilities or []):
        code = _capability_code(item)
        if code is not None:
            codes.add(code)
            codes.update(ABILITY_TO_RIGHTS.get(code, ()))
    return codes


def command_permitted_by_vehicle(command: str, right_codes: set[int]) -> bool:
    """True se o veículo tem o direito exigido pelo comando. Fail-open: sem dados
    de capacidade (`right_codes` vazio) ou comando sem direito mapeado, não filtra
    — preserva o comportamento anterior para não sumir comando de quem já funciona."""
    required = COMMAND_REQUIRED_RIGHT.get(command)
    if required is None or not right_codes:
        return True
    return required in right_codes


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
    return sanitize_log(message, 900)


def safe_remote_result_summary(value: Any) -> dict[str, Any]:
    """Return a tiny allow-listed diagnostic view of a library command result.

    Remote-control responses can contain opaque identifiers and future fields.
    Never serialize the whole object: only status-like values are retained.
    """
    summary: dict[str, Any] = {
        "type": type(value).__name__,
        "returned": value is not None,
        "payload": "none" if value is None else "opaque",
    }
    if value is None:
        return summary

    if isinstance(value, bool):
        summary.update({"payload": "scalar", "value": value})
        return summary
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        summary.update({"payload": "scalar", "value": value})
        return summary
    if isinstance(value, str):
        summary.update({"payload": "scalar", "value": clean_message(value)[:160]})
        return summary

    mapping: dict[str, Any] = {}
    if isinstance(value, dict):
        mapping = value
    elif is_dataclass(value):
        try:
            raw = asdict(value)
            mapping = raw if isinstance(raw, dict) else {}
        except Exception:
            mapping = {}
    else:
        for exporter in ("model_dump", "dict"):
            fn = getattr(value, exporter, None)
            if callable(fn):
                try:
                    raw = fn()
                    if isinstance(raw, dict):
                        mapping = raw
                        break
                except Exception:
                    pass
        if not mapping:
            for name in (
                "result", "code", "status", "success", "accepted", "completed",
                "message", "reason", "description", "data", "remote_ctl_id",
                "remoteCtlId", "remote_control_id",
            ):
                try:
                    if hasattr(value, name):
                        mapping[name] = getattr(value, name)
                except Exception:
                    pass

    if not mapping:
        return summary

    summary["payload"] = "mapping"
    allowed = {
        "result", "code", "status", "success", "accepted", "completed",
        "message", "reason", "description",
    }
    identifier_aliases = {"remotectlid", "remote_ctl_id", "remotecontrolid", "remote_control_id"}

    def add_fields(source: dict[str, Any], prefix: str = "") -> None:
        for raw_key, raw_value in source.items():
            key = str(raw_key or "").strip()
            normalized = re.sub(r"[^a-z0-9_]", "", key.lower())
            if normalized in identifier_aliases:
                summary[prefix + "remote_control_id_present"] = bool(raw_value)
                continue
            canonical = normalized.replace("_", "")
            matched = None
            for candidate in allowed:
                if canonical == candidate.replace("_", ""):
                    matched = candidate
                    break
            if matched is None:
                continue
            out_key = prefix + matched
            if isinstance(raw_value, bool) or raw_value is None:
                summary[out_key] = raw_value
            elif isinstance(raw_value, (int, float)):
                summary[out_key] = raw_value
            elif isinstance(raw_value, str):
                summary[out_key] = clean_message(raw_value)[:160]
            else:
                summary[out_key] = type(raw_value).__name__

    add_fields(mapping)
    nested = mapping.get("data")
    if isinstance(nested, dict):
        add_fields(nested, "data_")
    response = mapping.get("response")
    if isinstance(response, dict):
        add_fields(response, "response_")
    return summary


def remote_result_signal(summary: dict[str, Any]) -> str:
    """Classify only explicit result evidence; absence remains unknown."""
    boolean_keys = (
        "success", "accepted", "completed",
        "data_success", "data_accepted", "data_completed",
        "response_success", "response_accepted", "response_completed",
    )
    booleans = [summary.get(key) for key in boolean_keys if isinstance(summary.get(key), bool)]
    if any(value is False for value in booleans):
        return "negative"
    if any(value is True for value in booleans):
        return "positive"

    for key in ("result", "code", "data_result", "data_code", "response_result", "response_code"):
        value = summary.get(key)
        if isinstance(value, (int, float)):
            return "positive" if value == 0 else "negative"
        if isinstance(value, str) and value.strip():
            token = value.strip().lower()
            if token in {"0", "ok", "success", "successful", "completed", "complete"}:
                return "positive"
            if token in {"1", "false", "failed", "failure", "error", "rejected", "denied"}:
                return "negative"
    return "unknown"


class ConnectorTemporaryError(RuntimeError):
    """Falha temporária da nuvem que deve ser tentada novamente."""


class ConnectorAuthenticationError(RuntimeError):
    """Credencial realmente recusada depois das tentativas de reautenticação."""


class ConnectorSessionExpiredError(ConnectorTemporaryError):
    """A sessão/token expirou, mas as credenciais não foram recusadas."""


class ConnectorLoginCooldownError(ConnectorTemporaryError):
    """A nuvem bloqueou novos logins temporariamente; não é senha inválida."""

    def __init__(self, message: str, retry_after_seconds: int = 135) -> None:
        super().__init__(message)
        # O valor imediato informado pela Leapmotor é preservado, enquanto o
        # coordenador global pode ampliar bloqueios consecutivos até 30 minutos.
        self.retry_after_seconds = max(30, min(1800, int(retry_after_seconds or 135)))


LOGIN_COOLDOWN_MARKERS = (
    "password error limit has reached maximum",
    "password error limit",
    "too many login attempts",
    "login attempt limit",
    "login limit has reached maximum",
    "try again in",
)


def login_cooldown_seconds(value: Any) -> int:
    message = clean_message(str(value)).lower()
    if not any(marker in message for marker in LOGIN_COOLDOWN_MARKERS):
        return 0
    match = re.search(r"try again in\s+(\d+)\s*(second|seconds|minute|minutes|hour|hours)", message)
    if not match:
        base_seconds = 120
    else:
        amount = max(1, int(match.group(1)))
        unit = match.group(2)
        multiplier = 1 if unit.startswith("second") else (60 if unit.startswith("minute") else 3600)
        base_seconds = amount * multiplier
    # Pequena margem para o relógio da nuvem, limitada a cinco minutos.
    return max(30, min(300, base_seconds + 15))


def is_login_cooldown_error(value: Any) -> bool:
    return login_cooldown_seconds(value) > 0


GENERAL_RATE_LIMIT_MARKERS = (
    "too many requests",
    "request limit",
    "rate limit",
    "rate-limit",
    "throttle",
    "temporarily blocked",
    "muitas solicitações",
    "limite de requisições",
)


def rate_limit_cooldown_seconds(value: Any, default_seconds: int = 900) -> int:
    message = clean_message(str(value)).lower()
    if login_cooldown_seconds(message) > 0:
        return 0
    if not any(marker in message for marker in GENERAL_RATE_LIMIT_MARKERS) and not re.search(r"(?:^|\D)429(?:\D|$)", message):
        return 0
    match = re.search(
        r"(?:retry[- ]?after|try again in|retry in)\s*[:=]?\s*(\d+)\s*(second|seconds|minute|minutes|hour|hours)?",
        message,
    )
    if match:
        amount = max(1, int(match.group(1)))
        unit = str(match.group(2) or "seconds")
        multiplier = 1 if unit.startswith("second") else (60 if unit.startswith("minute") else 3600)
        delay = amount * multiplier + 15
    else:
        delay = int(default_seconds or 900)
    # Um bloqueio geral é reavaliado de forma moderada. Não deixe uma resposta
    # sem Retry-After congelar a conta por seis horas.
    return max(300, min(3600, delay))


TRANSIENT_CLOUD_MARKERS = (
    "information verification failed",
    "please try again later",
    "try again later",
    "temporarily unavailable",
    "temporary unavailable",
    "service unavailable",
    "gateway timeout",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "remote disconnected",
    "too many requests",
    "too many login attempts",
    "password error limit has reached maximum",
    "login attempt limit",
    "rate limit",
    "request limit",
    "token expired",
    "session expired",
    "login expired",
    "invalid token",
    "bad gateway",
    "failed to issue certificate",
    "could not issue certificate",
    "certificate issuance failed",
    "certificate service unavailable",
    "http 502",
    "http 503",
    "http 504",
)

AUTHENTICATION_MARKERS = (
    "incorrect password",
    "wrong password",
    "invalid password",
    "invalid credentials",
    "credential invalid",
    "authentication failed",
    "account locked",
    "account disabled",
    "certificate invalid",
    "certificate expired",
    "unauthorized",
)


def is_transient_cloud_error(value: Any) -> bool:
    message = clean_message(str(value)).lower()
    return any(marker in message for marker in TRANSIENT_CLOUD_MARKERS)


def is_session_expired_error(value: Any) -> bool:
    message = clean_message(str(value)).lower()
    return any(marker in message for marker in (
        "token expired", "session expired", "login expired", "invalid token",
        "token is invalid", "expired token", "authentication token expired",
    ))


def is_authentication_error(value: Any) -> bool:
    message = clean_message(str(value)).lower()
    return not is_transient_cloud_error(message) and any(marker in message for marker in AUTHENTICATION_MARKERS)


def is_command_certificate_session_error(value: Any) -> bool:
    """True only for an expired session rejected *before* command dispatch.

    leapmotor-api may fail either while synchronizing the command certificate or
    during its protected remote-verification step. Both happen before /remote/ctl
    is allowed to submit the vehicle action, so one clean-session retry is safe.
    Result-poll token failures are deliberately excluded because the action may
    already have been accepted by the cloud.
    """
    message = clean_message(str(value)).lower()
    pre_dispatch_stage = any(marker in message for marker in (
        'cert sync failed', 'certificate sync failed', 'failed to issue certificate',
        'could not issue certificate', 'certificate issuance failed',
        'remote verify failed', 'remote verification failed',
    ))
    invalid_session = any(marker in message for marker in (
        'token is invalid', 'invalid token', 'token expired', 'session expired', 'login expired',
    ))
    post_dispatch_result = any(marker in message for marker in (
        'remote control result failed', 'timed out waiting for remote control result',
    ))
    return pre_dispatch_stage and invalid_session and not post_dispatch_result


def reconnect_message(value: Any) -> str:
    message = clean_message(str(value))
    return (
        "A nuvem Leapmotor recusou temporariamente a validação. "
        "O Gateway preservou as credenciais protegidas e tentará reconectar automaticamente. "
        f"Detalhe: {message}"
    )[:900]


_PACKAGE_VERSION_CACHED = False
_PACKAGE_VERSION_VALUE: str | None = None


def package_version() -> str | None:
    """Versão da biblioteca, resolvida uma única vez por processo.

    1.12.50 — importlib.metadata.version varre o sys.path e lê os arquivos
    dist-info a cada chamada. Isso acontecia em todo /health/details e em todo
    payload de telemetria; em disco mecânico era I/O no caminho quente. A versão
    só muda com reinstalação do add-on, que reinicia o processo.
    """
    global _PACKAGE_VERSION_CACHED, _PACKAGE_VERSION_VALUE
    if not _PACKAGE_VERSION_CACHED:
        try:
            _PACKAGE_VERSION_VALUE = version("leapmotor-api")
        except PackageNotFoundError:
            _PACKAGE_VERSION_VALUE = None
        _PACKAGE_VERSION_CACHED = True
    return _PACKAGE_VERSION_VALUE


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
    """Carimbo ISO **sempre com fuso**, para nenhum consumidor ter de adivinhar.

    1.12.61 — a `leapmotor_api` entrega `collect_time`/`create_time` como
    datetime ingênuo (`strptime` com `noqa: DTZ007`), e devolver `isoformat()` cru
    produzia string sem offset. Cada lado então presumia um fuso diferente: o site
    lia como hora local (`strtotime`) e acertava a idade; o portão de frescura da
    confirmação presumia UTC e deslocava o carimbo pelo offset do host, medido em
    ~10800s num host -03:00 — o suficiente para descartar 100% das amostras e
    nenhum comando ser confirmado. Anexar o fuso local aqui resolve na origem.
    """
    if isinstance(value, datetime):
        return value.astimezone().isoformat() if value.tzinfo is None else value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).astimezone().isoformat()
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


def tire_temperature_c(value: Any) -> float | None:
    """Normalize a temperature only when the vehicle actually reports one."""
    parsed = numeric(value)
    if parsed is None:
        return None
    if abs(parsed) > 200 and abs(parsed) <= 2000:
        parsed /= 10
    return round(parsed, 1) if -60 <= parsed <= 150 else None


def tire_metrics(tires: Any, status: Any) -> tuple[dict[str, float | None], dict[str, float]]:
    """Keep pressure compatibility and publish optional per-wheel temperature."""
    pressures = attribute(tires, "all_bar", {})
    if not isinstance(pressures, dict):
        pressures = {}
    scalars = object_scalar_map(tires)
    for key, value in object_scalar_map(attribute(status, "raw", {})).items():
        scalars.setdefault(key, value)
    aliases = {
        "front_left": ("leftFrontTireTemperature", "frontLeftTireTemperature", "leftFrontTireTemp", "frontLeftTireTemp", "lfTireTemperature", "lfTireTemp"),
        "front_right": ("rightFrontTireTemperature", "frontRightTireTemperature", "rightFrontTireTemp", "frontRightTireTemp", "rfTireTemperature", "rfTireTemp"),
        "rear_left": ("leftRearTireTemperature", "rearLeftTireTemperature", "leftRearTireTemp", "rearLeftTireTemp", "lrTireTemperature", "rlTireTemp"),
        "rear_right": ("rightRearTireTemperature", "rearRightTireTemperature", "rightRearTireTemp", "rearRightTireTemp", "rrTireTemperature", "rrTireTemp"),
    }
    temperatures: dict[str, float] = {}
    for position, names in aliases.items():
        direct = first_numeric(*(attribute(tires, name, None) for name in names))
        value = tire_temperature_c(direct if direct is not None else mapping_pick(scalars, names))
        if value is not None:
            temperatures[position] = value
    return {key: numeric(value) for key, value in pressures.items()}, temperatures


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


CLIMATE_COMFORT_SIGNAL_IDS = frozenset({
    "49", "50", "1349", "1624", "1816",
    "1938", "1939", "1940", "1941", "1943", "1945", "1946", "1949",
    "2100", "2101", "2118", "2119",
    "2183", "2184", "2669", "2681", "3713",
})

def safe_climate_comfort_raw_signals(raw: Any, max_items: int = 32) -> dict[str, Any]:
    result: dict[str, Any] = {}
    def walk(node: Any, depth: int) -> None:
        if len(result) >= max_items or depth > 7:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key)
                if key_text in CLIMATE_COMFORT_SIGNAL_IDS and isinstance(value, (str, int, float, bool)):
                    result["signal." + key_text] = value
                if isinstance(value, (dict, list, tuple)):
                    walk(value, depth + 1)
        elif isinstance(node, (list, tuple)):
            for value in node[:64]:
                if isinstance(value, (dict, list, tuple)):
                    walk(value, depth + 1)
    walk(raw, 0)
    return dict(sorted(result.items()))

_CLIMATE_COMFORT_RAW_PROBE_LAST_SIGNATURE: str | None = None


def log_climate_comfort_raw_probe(raw_signals: dict[str, Any]) -> bool:
    # Probe RAW no ponto comprovado da coleta; loga vazio uma vez e mudanças depois.
    global _CLIMATE_COMFORT_RAW_PROBE_LAST_SIGNATURE
    payload = dict(sorted((raw_signals or {}).items()))
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default)
    signature = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if signature == _CLIMATE_COMFORT_RAW_PROBE_LAST_SIGNATURE:
        return False
    _CLIMATE_COMFORT_RAW_PROBE_LAST_SIGNATURE = signature
    connector_log(
        logging.INFO,
        "CLIMATE_RAW_PROBE raw_candidates=%s",
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default),
    )
    return True


_CLIMATE_COMFORT_DIAG_LAST_SIGNATURE: str | None = None


def log_climate_comfort_diag(
    climate_state: dict[str, Any],
    seat_state: dict[str, Any],
    mirrors_state: dict[str, Any],
    raw_signals: dict[str, Any] | None = None,
) -> bool:
    # Somente campos tipados/allow-listed; status.raw nunca entra aqui.
    global _CLIMATE_COMFORT_DIAG_LAST_SIGNATURE
    climate_keys = (
        "on", "left_temperature_c", "right_temperature_c", "fan_level",
        "mode", "operate_mode", "cooling_and_heating", "recirculation",
        "windshield_defrost",
    )
    seat_keys = ("steering_wheel_heating", "steering_wheel_minutes")
    mirror_keys = ("left_heating", "right_heating")
    snapshot = {
        "climate": {key: climate_state[key] for key in climate_keys if key in climate_state},
        "comfort": {key: seat_state[key] for key in seat_keys if key in seat_state},
        "mirrors": {key: mirrors_state[key] for key in mirror_keys if key in mirrors_state},
        "raw_candidates": dict(sorted((raw_signals or {}).items())),
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default)
    signature = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if signature == _CLIMATE_COMFORT_DIAG_LAST_SIGNATURE:
        return False
    _CLIMATE_COMFORT_DIAG_LAST_SIGNATURE = signature
    connector_log(
        logging.INFO,
        "CLIMATE_COMFORT_DIAG climate=%s comfort=%s mirrors=%s raw_candidates=%s",
        json.dumps(snapshot["climate"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default),
        json.dumps(snapshot["comfort"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default),
        json.dumps(snapshot["mirrors"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default),
        json.dumps(snapshot["raw_candidates"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default),
    )
    return True


def window_open(value: Any) -> bool | None:
    if value is None:
        return None
    number = numeric(value)
    if number is not None:
        return number > 0
    return bool_or_none(value)


def effective_window_open(position: Any, explicit_status: Any) -> bool | None:
    status = first_bool(explicit_status)
    if status is not None:
        return status
    if position is not None:
        return window_open(position)
    return None


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


WINDOW_DIAG_SENSITIVE_TOKENS = frozenset({
    "vin", "token", "password", "passwd", "secret", "credential", "certificate",
    "privatekey", "private_key", "email", "account", "latitude", "longitude",
    "location", "gps", "address", "deviceid", "device_id",
})
WINDOW_DIAG_HINT_TOKENS = ("window", "glass", "vidro")
WINDOW_DIAG_SIGNAL_IDS = frozenset({
    "3727", "3728",
    "1879", "1880",
    "1693", "1694",
    "1695", "1696",
})
_WINDOW_RAW_DIAG_LAST_SIGNATURE: str | None = None


def _window_diag_scalar(value: Any) -> bool | int | float | str | None:
    raw = value_of(value)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw if -100000 <= raw <= 100000 else None
    if isinstance(raw, float):
        if raw != raw or abs(raw) > 100000:
            return None
        return round(raw, 4)
    if isinstance(raw, str):
        text = raw.strip()
        if len(text) > 32:
            return None
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            return text
        if text.lower() in {"true", "false", "open", "opened", "close", "closed", "unknown"}:
            return text.lower()
    return None


def safe_window_raw_signals(raw: Any, max_items: int = 48) -> dict[str, Any]:
    """Return a bounded, sanitized subset of window-like scalar signals."""
    result: dict[str, Any] = {}

    def walk(node: Any, path: tuple[str, ...], depth: int) -> None:
        if len(result) >= max_items or depth > 7:
            return
        if isinstance(node, dict):
            for raw_key, candidate in node.items():
                if len(result) >= max_items:
                    return
                key = str(raw_key)[:80]
                normalized_key = re.sub(r"[^a-z0-9_]+", "", key.lower())
                if any(token in normalized_key for token in WINDOW_DIAG_SENSITIVE_TOKENS):
                    continue
                next_path = path + (key,)
                normalized_path = re.sub(r"[^a-z0-9_]+", "", ".".join(next_path).lower())
                scalar = _window_diag_scalar(candidate)
                is_named_window = any(token in normalized_path for token in WINDOW_DIAG_HINT_TOKENS)
                is_known_window_signal = normalized_key in WINDOW_DIAG_SIGNAL_IDS
                if scalar is not None and (is_named_window or is_known_window_signal):
                    result[".".join(part[:80] for part in next_path)[:240]] = scalar
                if isinstance(candidate, (dict, list, tuple)):
                    walk(candidate, next_path, depth + 1)
        elif isinstance(node, (list, tuple)):
            for index, candidate in enumerate(node[:64]):
                if len(result) >= max_items:
                    return
                walk(candidate, path + (f"[{index}]",), depth + 1)

    walk(raw, tuple(), 0)
    return dict(sorted(result.items()))


def log_window_telemetry_diag(
    window_positions: dict[str, Any],
    window_state: dict[str, Any],
    raw_signals: dict[str, Any],
) -> bool:
    global _WINDOW_RAW_DIAG_LAST_SIGNATURE
    snapshot = {
        "positions": compact_mapping(window_positions),
        "states": compact_mapping(window_state),
        "raw_candidates": raw_signals,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default)
    signature = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if signature == _WINDOW_RAW_DIAG_LAST_SIGNATURE:
        return False
    _WINDOW_RAW_DIAG_LAST_SIGNATURE = signature
    connector_log(
        logging.INFO,
        "WINDOW_TELEMETRY_DIAG positions=%s states=%s raw_candidates=%s",
        json.dumps(snapshot["positions"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default),
        json.dumps(snapshot["states"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default),
        json.dumps(snapshot["raw_candidates"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default),
    )
    return True


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
        "version": 9,
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
        if "c10" in normalized or normalized in {"t03", "leapmotort03"}:
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



_IMAGE_LAST_HASH: dict[str, str] = {}
_IMAGE_PACKAGE_CACHE: dict[str, tuple[float, Any, str, Path]] = {}
_IMAGE_RENDER_CACHE: dict[str, tuple[float, bytes, str, dict[str, Any]]] = {}
_IMAGE_METADATA_CACHE: dict[str, dict[str, Any]] = {}
_IMAGE_DEBUG_LAST_HASH: dict[str, str] = {}
# 1.12.40 — última assinatura visual cujos BYTES já foram entregues ao site.
# `_IMAGE_LAST_HASH` guarda o hash da imagem; este guarda o ESTADO que ela
# retrata, que é o que decide se o desenho ainda descreve o veículo.
_IMAGE_LAST_SIGNATURE: dict[str, str] = {}


# 1.12.95 — a figura final continua lossless, mas o compressor não precisa
# gastar vários segundos procurando a menor representação possível.
IMAGE_WEBP_METHOD = 0
IMAGE_RENDER_CONTRACT_VERSION = 16


class _LazyOfficialImagePackage:
    """Indexa o ZIP agora e decodifica cada camada somente quando usada."""

    def __init__(self, zip_bytes: bytes) -> None:
        self._zip_bytes = bytes(zip_bytes)
        self._entries: dict[str, str] = {}
        self._decoded: dict[str, Any] = {}
        self._lock = threading.RLock()
        with zipfile.ZipFile(io.BytesIO(self._zip_bytes), "r") as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                lower = info.filename.lower()
                if not lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    continue
                basename = info.filename.rsplit("/", 1)[-1]
                self._entries[basename] = info.filename
        if "carpic_body.png" not in self._entries:
            raise ValueError("Package missing carpic_body.png")

    @classmethod
    def from_zip(cls, zip_bytes: bytes) -> "_LazyOfficialImagePackage":
        return cls(zip_bytes)

    @property
    def layer_names(self) -> list[str]:
        return sorted(self._entries)

    @property
    def decoded_layer_count(self) -> int:
        with self._lock:
            return len(self._decoded)

    def _image(self, name: str) -> Any | None:
        with self._lock:
            cached = self._decoded.get(name)
            entry = self._entries.get(name)
        if cached is not None:
            return cached
        if not entry:
            return None
        from PIL import Image
        with zipfile.ZipFile(io.BytesIO(self._zip_bytes), "r") as archive:
            raw = archive.read(entry)
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
        image.load()
        with self._lock:
            existing = self._decoded.get(name)
            if existing is not None:
                return existing
            self._decoded[name] = image
        return image

    def get_tripsum(self) -> Any | None:
        return self._image("carpic_for_tripsum.png")

    def _composite_layers(self, layer_names: list[str]) -> Any:
        from PIL import Image
        body = self._image("carpic_body.png")
        if body is None:
            raise ValueError("Package missing carpic_body.png")
        canvas = Image.new("RGBA", body.size, (0, 0, 0, 0))
        for name in layer_names:
            layer = self._image(name)
            if layer is not None:
                canvas = Image.alpha_composite(canvas, layer)
        return canvas

    @staticmethod
    def _export(canvas: Any, fmt: str = "PNG") -> bytes:
        from PIL import Image
        buffer = io.BytesIO()
        if fmt.upper() == "JPEG":
            rgb = Image.new("RGB", canvas.size, (0, 0, 0))
            rgb.paste(canvas, mask=canvas.split()[3])
            rgb.save(buffer, format="JPEG", quality=90)
        elif fmt.upper() == "PNG":
            canvas.save(buffer, format="PNG", compress_level=1)
        else:
            canvas.save(buffer, format=fmt.upper())
        return buffer.getvalue()

    def compose(self, status: Any = None, *, charge_frame: int = 2, format: str = "PNG") -> bytes:
        stack = _layer_stack_from_status(status, charge_frame)
        return self._export(self._composite_layers(stack), format)

    def compose_animated(self, status: Any = None, *, frame_duration: int = 200) -> tuple[bytes, str]:
        from PIL import Image
        battery = getattr(status, "battery", None) if status is not None else None
        charging = bool(
            getattr(battery, "is_charging", False)
            or (getattr(status, "is_charging", False) if status is not None else False)
        )
        if not charging:
            return self.compose(status), "image/png"
        stack = _layer_stack_from_status(status, 2)
        base_layers = [
            name for name in stack
            if not name.startswith("carpic_charge") or name == "carpic_charge_open.png"
        ]
        base_canvas = self._composite_layers(base_layers)
        frames: list[Any] = []
        for frame_number in range(2, 16):
            charge_layer = self._image(f"carpic_charge{frame_number}.png")
            frame = Image.alpha_composite(base_canvas, charge_layer) if charge_layer is not None else base_canvas.copy()
            frames.append(frame)
        buffer = io.BytesIO()
        frames[0].save(
            buffer, format="WEBP", save_all=True, append_images=frames[1:],
            duration=frame_duration, loop=0, lossless=True, quality=100,
            method=IMAGE_WEBP_METHOD,
        )
        return buffer.getvalue(), "image/webp"


def should_defer_official_image(
    *,
    include_secondary_network: bool,
    manual_waiting: bool,
    signature_changed: bool,
) -> bool:
    """Decide se a imagem oficial pode ficar para a próxima leitura.

    Três regras, em ordem de precedência:

    1. Comando manual aguardando SEMPRE adia — é a garantia da 1.12.28: o
       pacote de imagem não pode segurar a conta na frente de um comando.
    2. Assinatura visual mudou: não adia. A composição anterior deixou de
       descrever o veículo, então ela e o estado passam a discordar na tela.
       Foi o defeito relatado em 01/08/2026 — porta aberta e fechada certas nos
       selos, e o desenho parado até alguém mandar um comando.
    3. Fora isso, o perfil FAST adia, como antes.
    """
    if manual_waiting:
        return True
    if signature_changed:
        return False
    return not include_secondary_network


_OFFICIAL_RENDER_COMPONENTS = {
    "front-left-open",
    "front-right-open",
    "rear-left-open",
    "rear-right-open",
    "trunk-open",
    "window-front-left-open",
    "window-rear-left-open",
    "plugged",
    "charging",
}


def _official_render_contract(
    visual_components: list[str],
    evidence: dict[str, Any],
) -> tuple[str, list[str], str]:
    """Return only the state that the official layer package can actually draw."""
    active = {
        str(component).strip().lower()
        for component in visual_components
        if str(component).strip().lower() in _OFFICIAL_RENDER_COMPONENTS
    }
    if evidence.get("active_charging") is True:
        render_state = "charging"
        active.discard("plugged")
        active.add("charging")
    elif evidence.get("plugged") is True:
        render_state = "plugged"
        active.discard("charging")
        active.add("plugged")
    else:
        render_state = "parked"
        active.discard("charging")
        active.discard("plugged")
    components = sorted(active)
    signature = "--".join([render_state] + [item for item in components if item != render_state])
    return render_state, components, signature


def _official_visual_status(render_components: list[str], render_state: str) -> Any:
    """Build the compositor input from the normalized visual contract.

    The cloud object can temporarily omit a door group. Passing that raw object to
    the upstream compositor turns an unknown sensor into a closed door. Building a
    status from the normalized active components prevents the image from reverting
    to closed while the visual contract still reports the opening.
    """
    active = set(render_components)
    front_left_open = "front-left-open" in active
    front_right_open = "front-right-open" in active
    rear_left_open = "rear-left-open" in active
    rear_right_open = "rear-right-open" in active
    doors = SimpleNamespace(
        lbcm_driver_door_status=front_left_open,
        rbcm_driver_door_status=front_right_open,
        lbcm_left_rear_door_status=rear_left_open,
        rbcm_right_rear_door_status=rear_right_open,
        bbcm_back_door_status="trunk-open" in active,
    )
    # O pacote oficial posiciona o vidro fechado na posição da porta fechada.
    # Quando uma porta abre, manter essa camada cria um reflexo/painel deslocado
    # na frente da abertura. A correção é somente visual: a telemetria original
    # do vidro continua intacta e apenas a composição omite o vidro fechado.
    windows = SimpleNamespace(
        left_front_window_percent=100 if front_left_open or "window-front-left-open" in active else 0,
        right_front_window_percent=100 if front_right_open or "window-front-right-open" in active else 0,
        left_rear_window_percent=100 if rear_left_open or "window-rear-left-open" in active else 0,
        right_rear_window_percent=100 if rear_right_open or "window-rear-right-open" in active else 0,
    )
    charging = render_state == "charging"
    plugged = render_state in {"charging", "plugged"}
    return SimpleNamespace(
        doors=doors,
        windows=windows,
        is_plugged=plugged,
        is_charging=charging,
        battery=SimpleNamespace(is_charging=charging),
    )


def _edge_alpha_ratio(image: Any) -> float:
    width, height = image.size
    if width < 2 or height < 2:
        return 1.0
    alpha = image.getchannel("A")
    pixels = alpha.load()
    samples: list[int] = []
    for x in range(width):
        samples.append(int(pixels[x, 0]))
        samples.append(int(pixels[x, height - 1]))
    for y in range(1, height - 1):
        samples.append(int(pixels[0, y]))
        samples.append(int(pixels[width - 1, y]))
    if not samples:
        return 0.0
    return sum(1 for value in samples if value > 12) / len(samples)


# 1.12.66 — a ordem de empilhamento vem dos PREFIXOS NUMÉRICOS do pacote
# oficial, lidos em 01/08/2026 na biblioteca do C10:
#
#   01 tailgate_open   02 body                 03 leftbehind_window_close
#   04 leftfront_window_close                  05 tailgate_close
#   06 hood_open       07 leftbehind_open      08 leftfront_open
#   09 rightbehind_open                        10 rightfront_open
#
# `leapmotor_api._build_layer_list()` inverte a ordem em dois pontos, e é daí
# que vinham os dois defeitos relatados pelo proprietário:
#
#   - `tailgate_open` DEPOIS do corpo → a tampa sobrepõe o carro;
#   - `*_window_close` DEPOIS das portas → o vidro e o caixilho da porta
#     fechada são carimbados sobre a porta aberta.
#
# Reproduzido lado a lado com as camadas reais e confirmado pelo proprietário.
# A biblioteca também pede cinco camadas `*_close` de porta e capô que NÃO
# existem neste pacote (só o corpo e sobreposições do que abre); elas eram
# ignoradas em silêncio por `_composite_layers`.
OFFICIAL_LAYER_ORDER: tuple[str, ...] = (
    "carpic_tailgate_open.png",
    "carpic_body.png",
    "carpic_leftbehind_window_close.png",
    "carpic_leftfront_window_close.png",
    "carpic_tailgate_close.png",
    "carpic_hood_open.png",
    "carpic_leftbehind_open.png",
    "carpic_leftfront_open.png",
    "carpic_rightbehind_open.png",
    "carpic_rightfront_open.png",
)


def official_layer_stack(
    *,
    trunk_open: bool = False,
    hood_open: bool = False,
    left_front_door_open: bool = False,
    left_rear_door_open: bool = False,
    right_front_door_open: bool = False,
    right_rear_door_open: bool = False,
    left_front_window_closed: bool = True,
    left_rear_window_closed: bool = True,
    charging: bool = False,
    plugged: bool = False,
    charge_frame: int | None = None,
) -> list[str]:
    """Monta a pilha de camadas na ordem do pacote oficial.

    Função pura: recebe só estados booleanos e devolve nomes de arquivo. É ela
    que o contrato exercita, porque a garantia é a ORDEM — não a expressão que
    hoje a implementa.
    """
    stack: list[str] = []

    # Lado direito (longe), abaixo do corpo. As camadas de porta FECHADA existem
    # no pacote que o gateway baixa da nuvem — omiti-las na 1.12.66 fez o carro
    # sair sem as laterais. Pacotes que não as tenham simplesmente as ignoram:
    # `_composite_layers` pula camada ausente.
    stack.append(
        "carpic_rightbehind_open.png" if right_rear_door_open else "carpic_rightbehind_close.png"
    )
    stack.append(
        "carpic_rightfront_open.png" if right_front_door_open else "carpic_rightfront_close.png"
    )

    # CORREÇÃO 1 — a tampa aberta vem ANTES do corpo (prefixo 01 contra 02).
    if trunk_open:
        stack.append("carpic_tailgate_open.png")
    stack.append("carpic_body.png")
    # `carpic_tailgate_close.png` NÃO entra. O corpo do pacote que o gateway usa
    # já traz a tampa fechada, e desenhá-la de novo a sobrepõe ao carro — foi o
    # que o dono viu na 1.12.67, com o porta-malas FECHADO. A camada existe no
    # pacote da página de admin com prefixo 05 e eu a deduzi dali; a biblioteca
    # nunca a acrescenta, e nisso ela está certa. Mover só o que está provado.
    stack.append("carpic_hood_close.png")
    if hood_open:
        stack.append("carpic_hood_open.png")

    # Lado esquerdo (perto), acima do corpo.
    # CORREÇÃO 2 — o vidro fechado só pode vir DEPOIS da porta quando a porta
    # está fechada. Com a porta aberta ele fica atrás dela; senão o caixilho é
    # carimbado sobre a porta aberta, que é o defeito recortado pelo dono.
    if left_rear_door_open:
        if left_rear_window_closed:
            stack.append("carpic_leftbehind_window_close.png")
        stack.append("carpic_leftbehind_open.png")
    else:
        stack.append("carpic_leftbehind_close.png")
        if left_rear_window_closed:
            stack.append("carpic_leftbehind_window_close.png")

    if left_front_door_open:
        if left_front_window_closed:
            stack.append("carpic_leftfront_window_close.png")
        stack.append("carpic_leftfront_open.png")
    else:
        stack.append("carpic_leftfront_close.png")
        if left_front_window_closed:
            stack.append("carpic_leftfront_window_close.png")
    # Camadas de carga são 13+ no pacote: sempre depois das portas.
    if charging:
        frame = charge_frame if charge_frame is not None and 2 <= charge_frame <= 15 else 2
        stack.append("carpic_charge_open.png")
        stack.append(f"carpic_charge{frame}.png")
    elif plugged:
        stack.append("carpic_charge_open.png")
        stack.append("carpic_charge1.png")
    return stack


def _layer_stack_from_status(visual_status: Any, charge_frame: int | None = None) -> list[str]:
    """Traduz o `VehicleStatus` da biblioteca para a pilha oficial."""
    doors = getattr(visual_status, "doors", None)
    windows = getattr(visual_status, "windows", None)
    battery = getattr(visual_status, "battery", None)

    def flag(source: Any, name: str) -> bool:
        return bool(getattr(source, name, False))

    def window_closed(name: str) -> bool:
        # Vidro ausente conta como fechado, que é o que o pacote desenha.
        return (getattr(windows, name, 0) or 0) == 0

    return official_layer_stack(
        trunk_open=flag(doors, "bbcm_back_door_status"),
        hood_open=flag(visual_status, "hood_open"),
        left_front_door_open=flag(doors, "lbcm_driver_door_status"),
        left_rear_door_open=flag(doors, "lbcm_left_rear_door_status"),
        right_front_door_open=flag(doors, "rbcm_driver_door_status"),
        right_rear_door_open=flag(doors, "rbcm_right_rear_door_status"),
        left_front_window_closed=window_closed("left_front_window_percent"),
        left_rear_window_closed=window_closed("left_rear_window_percent"),
        charging=flag(battery, "is_charging") or flag(visual_status, "is_charging"),
        plugged=flag(visual_status, "is_plugged"),
        charge_frame=charge_frame,
    )


def _compose_official_frame(
    package: Any,
    visual_status: Any,
    charge_frame: int | None = None,
) -> tuple[bytes, int]:
    """Compõe um quadro na ordem oficial de camadas.

    Antes da 1.12.66 esta função delegava a ordem a `package.compose()` e depois
    tentava remendar o artefato do vidro repintando um polígono de frações
    fixas. O remendo saiu: com o vidro empilhado atrás da porta, como manda o
    prefixo oficial, não há artefato para apagar.
    """
    try:
        stack = _layer_stack_from_status(visual_status, charge_frame)
        canvas = package._composite_layers(stack)
        return package._export(canvas, "PNG"), 0
    except Exception as exc:
        connector_log(
            logging.WARNING,
            "Composição oficial por camadas falhou (%s); usando a composição da biblioteca.",
            type(exc).__name__,
        )

    compose_options: dict[str, Any] = {"format": "PNG"}
    if charge_frame is not None:
        compose_options["charge_frame"] = charge_frame
    return package.compose(visual_status, **compose_options), 0


def _encode_official_composite(raw_image: bytes, media_type: str = "image/png") -> tuple[bytes, dict[str, Any]]:
    """Preserve the exact official canvas, alpha, shadow and wheel area.

    The package already contains aligned full-canvas layers. Cropping, edge flood-fill
    and white flattening altered the official composition and could remove tires,
    shadows or parts below an opened door. This encoder validates the image and
    exports the complete canvas without interpreting its pixels.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(raw_image))
    width, height = image.size
    if width < 64 or height < 64 or width > 4096 or height > 4096:
        raise ValueError("Dimensões da composição oficial fora do limite.")

    is_animated = bool(getattr(image, "is_animated", False)) and int(getattr(image, "n_frames", 1)) > 1
    if is_animated and media_type.lower() == "image/webp":
        output = raw_image
        output_format = "webp-lossless-animated-official"
        frame_count = int(getattr(image, "n_frames", 1))
    else:
        rgba = image.convert("RGBA")
        buffer = io.BytesIO()
        rgba.save(buffer, format="WEBP", lossless=True, quality=100, method=IMAGE_WEBP_METHOD)
        output = buffer.getvalue()
        output_format = "webp-lossless-rgba-official"
        frame_count = 1

    if len(output) < 512 or len(output) > 2_500_000:
        raise ValueError("A composição oficial ficou fora do limite permitido.")
    return output, {
        "edge_alpha_before": round(_edge_alpha_ratio(image.convert("RGBA")), 4),
        "edge_alpha_after": round(_edge_alpha_ratio(image.convert("RGBA")), 4),
        "removed_pixels": 0,
        "removed_percent": 0.0,
        "cropped": False,
        "output_width": width,
        "output_height": height,
        "format": output_format,
        "background": "transparent-official",
        "alpha_flattened": False,
        "frame_count": frame_count,
        "official_canvas_preserved": True,
    }


def _compose_official_output(package: Any, visual_status: Any, render_state: str) -> tuple[bytes, str, dict[str, Any]]:
    """Return the official static or animated composition without local cropping."""
    raw: bytes
    media_type = "image/png"
    glass_restored_pixels = 0
    if render_state == "charging":
        animated = getattr(package, "compose_animated", None)
        front_left_open = bool(getattr(getattr(visual_status, "doors", None), "lbcm_driver_door_status", False))
        if callable(animated) and not front_left_open:
            result = animated(visual_status, frame_duration=180)
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bytes):
                raw = result[0]
                media_type = str(result[1] or "image/webp")
            else:
                raw = package.compose(visual_status, charge_frame=2, format="PNG")
        else:
            # Compatibility with older library builds: build the official frames
            # from the same package coordinates and preserve the complete canvas.
            from PIL import Image
            frames = []
            for frame_number in range(2, 16):
                frame_raw, frame_restored = _compose_official_frame(
                    package,
                    visual_status,
                    charge_frame=frame_number,
                )
                glass_restored_pixels += frame_restored
                frames.append(Image.open(io.BytesIO(frame_raw)).convert("RGBA"))
            buffer = io.BytesIO()
            frames[0].save(
                buffer,
                format="WEBP",
                save_all=True,
                append_images=frames[1:],
                duration=180,
                loop=0,
                lossless=True,
                quality=100,
                method=IMAGE_WEBP_METHOD,
            )
            raw = buffer.getvalue()
            media_type = "image/webp"
    else:
        raw, glass_restored_pixels = _compose_official_frame(package, visual_status)
    if not isinstance(raw, bytes):
        raise ValueError("A biblioteca não retornou a composição oficial.")
    output, metadata = _encode_official_composite(raw, media_type)
    metadata["open_door_glass_restored"] = glass_restored_pixels > 0
    metadata["open_door_glass_restored_pixels"] = glass_restored_pixels
    return output, "image/webp", metadata

def _debug_safe_name(value: str, index: int) -> str:
    raw = Path(str(value or "layer")).name.lower()
    stem = re.sub(r"[^a-z0-9._-]+", "-", raw).strip(".-_") or f"layer-{index:02d}"
    stem = re.sub(r"[a-f0-9]{20,}", "redacted", stem)
    if not stem.endswith((".webp", ".png", ".jpg", ".jpeg")):
        stem += ".webp"
    base = stem.rsplit(".", 1)[0][:70]
    return f"{index:02d}-{base}.webp"


def _debug_webp(raw: bytes, background: tuple[int, int, int] | None = None, max_side: int = 760) -> tuple[bytes, int, int] | None:
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
        if image.width < 8 or image.height < 8 or image.width > 8192 or image.height > 8192:
            return None
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if background is not None:
            canvas = Image.new("RGB", image.size, background)
            canvas.paste(image.convert("RGB"), mask=image.getchannel("A"))
            image_out = canvas
        else:
            image_out = image
        buffer = io.BytesIO()
        image_out.save(buffer, format="WEBP", quality=90, method=6, lossless=False)
        data = buffer.getvalue()
        if len(data) < 128 or len(data) > 420_000:
            return None
        return data, image.width, image.height
    except Exception:
        return None


def _official_debug_payload(
    remote_id: str,
    package_file: Path,
    package: Any,
    visual_status: Any,
    picture_key_hash: str,
    render_layer_signature: str,
    render_components: list[str],
    captured_at: str,
    force: bool = False,
) -> dict[str, Any] | None:
    """Create a small sanitized gallery of the image layers received from the API.

    No VIN, account identifier, credentials or raw cloud payload are included. The
    gallery is normally emitted when the package/state combination changes; an authenticated settings test may force a safe resend.
    """
    try:
        package_bytes = package_file.read_bytes()
        package_hash = hashlib.sha256(package_bytes).hexdigest()
        debug_hash = hashlib.sha256(f"{package_hash}|{render_layer_signature}|debug-v1".encode()).hexdigest()
        if not force and _IMAGE_DEBUG_LAST_HASH.get(remote_id) == debug_hash:
            return None

        files: list[dict[str, Any]] = []
        total_bytes = 0
        max_total = 1_350_000

        raw_composite = package.compose(visual_status, format="PNG")
        if isinstance(raw_composite, bytes):
            previews = [
                ("preview-transparent.webp", None, "preview-transparent"),
                ("preview-white.webp", (255, 255, 255), "preview-white"),
                ("preview-dark.webp", (12, 25, 42), "preview-dark"),
            ]
            for name, background, kind in previews:
                converted = _debug_webp(raw_composite, background=background, max_side=860)
                if converted is None:
                    continue
                data, width, height = converted
                if total_bytes + len(data) > max_total:
                    break
                total_bytes += len(data)
                files.append({
                    "name": name,
                    "kind": kind,
                    "mime": "image/webp",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "width": width,
                    "height": height,
                    "data_base64": base64.b64encode(data).decode("ascii"),
                })

        with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as archive:
            candidates = []
            for info in archive.infolist():
                if info.is_dir() or info.file_size <= 0 or info.file_size > 12 * 1024 * 1024:
                    continue
                lower = info.filename.lower()
                if not lower.endswith((".png", ".webp", ".jpg", ".jpeg")):
                    continue
                score = 0
                for token, weight in (
                    ("body", 100), ("base", 90), ("door", 80), ("open", 75),
                    ("window", 70), ("charge", 65), ("tail", 60), ("trunk", 60),
                    ("trip", 40), ("close", 20), ("carpic", 10),
                ):
                    if token in lower:
                        score += weight
                candidates.append((score, info.filename, info))
            candidates.sort(key=lambda item: (-item[0], item[1].lower()))
            used_names: set[str] = set()
            for index, (_score, original_name, info) in enumerate(candidates[:28], start=1):
                if len(files) >= 22 or total_bytes >= max_total:
                    break
                raw = archive.read(info)
                converted = _debug_webp(raw, background=None, max_side=760)
                if converted is None:
                    continue
                data, width, height = converted
                if total_bytes + len(data) > max_total:
                    continue
                safe_name = _debug_safe_name(original_name, index)
                suffix = 1
                base_name = safe_name
                while safe_name in used_names:
                    suffix += 1
                    safe_name = base_name[:-5] + f"-{suffix}.webp"
                used_names.add(safe_name)
                total_bytes += len(data)
                original_basename = Path(original_name).name[:120]
                original_basename = re.sub(r"[a-fA-F0-9]{20,}", "[redacted]", original_basename)
                files.append({
                    "name": safe_name,
                    "kind": "layer",
                    "original_name": original_basename,
                    "mime": "image/webp",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "width": width,
                    "height": height,
                    "data_base64": base64.b64encode(data).decode("ascii"),
                })

        if not files:
            return None
        _IMAGE_DEBUG_LAST_HASH[remote_id] = debug_hash
        return {
            "schema": 1,
            "source": "leapmotor-picture-package-sanitized",
            "package_hash": package_hash,
            "picture_key_hash": picture_key_hash if re.fullmatch(r"[a-f0-9]{64}", picture_key_hash or "") else None,
            "render_layer_signature": render_layer_signature,
            "render_components": render_components,
            "captured_at": captured_at,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "files": files,
            "file_count": len(files),
            "total_bytes": total_bytes,
        }
    except Exception as exc:
        print(f"Leap Hub: diagnóstico das camadas oficiais indisponível ({type(exc).__name__}).", file=sys.stderr)
        return None


def charging_evidence(status: Any) -> dict[str, Any]:
    battery = attribute(status, "battery")
    driving = attribute(status, "driving")
    raw_charging = bool_or_none(attribute(status, "is_charging"))
    top_plugged = bool_or_none(attribute(status, "is_plugged"))
    fast_connector = first_bool(attribute(battery, "is_charge_fast_gun_insert"), attribute(battery, "dc_input_fast_charge"))
    slow_connector = first_bool(attribute(battery, "is_charge_slow_gun_insert"), attribute(battery, "ac_input_slow_charge"))
    connector_values = [value for value in (fast_connector, slow_connector) if value is not None]
    connector_known = bool(connector_values)
    connector_inserted = fast_connector is True or slow_connector is True
    connectors_explicitly_out = connector_known and not connector_inserted
    parked = bool_or_none(attribute(status, "is_parked"))
    speed = first_numeric(attribute(driving, "speed"))
    regenerating = bool_or_none(attribute(status, "is_regening"))
    completed = bool_or_none(attribute(battery, "charge_completed"))
    state_text = str(value_of(attribute(battery, "charge_state")) or "").strip().lower()
    power = first_numeric(attribute(battery, "charging_power_kw"))
    current = first_numeric(attribute(battery, "charging_current"), attribute(battery, "charge_current"))
    voltage = first_numeric(attribute(battery, "charging_voltage"), attribute(battery, "charge_voltage"))
    external_power = bool(
        (power is not None and abs(power) >= 0.25)
        or (current is not None and voltage is not None and abs(current) >= 0.5 and abs(voltage) >= 50.0)
    )
    moving = bool((speed is not None and speed > 1) or parked is False)
    state_says_charging = "charging" in state_text and "not" not in state_text
    state_says_regen = "regen" in state_text

    if regenerating is True or state_says_regen or (moving and raw_charging is True and not connector_inserted):
        state = "regenerating"
        active = False
        plugged = connector_inserted or top_plugged is True
    elif connectors_explicitly_out:
        # Os sinais físicos dos conectores são mais específicos que o booleano
        # genérico is_plugged/is_charging, que pode permanecer defasado na nuvem.
        state = "not_charging"
        active = False
        plugged = False
        external_power = False
    else:
        if connector_known:
            # Quando os sensores físicos existem, eles são a fonte de verdade.
            plugged = connector_inserted
            active_signal = raw_charging is True or state_says_charging or external_power
            active = bool(active_signal and plugged and not moving)
        else:
            # Booleanos genéricos da nuvem podem permanecer presos no último estado.
            # Sem confirmação AC/DC, só desenhamos cabo/carga quando há potência
            # elétrica externa mensurável nesta leitura.
            plugged = bool(external_power)
            active = bool(external_power and not moving)
        if active:
            state = "charging"
        elif completed is True or "finish" in state_text or "complete" in state_text:
            state = "completed" if plugged else "not_charging"
        elif plugged:
            state = "plugged"
        else:
            state = "not_charging"

    return compact_mapping({
        "state": state,
        "active_charging": active,
        "plugged": plugged,
        "raw_is_charging": raw_charging,
        "raw_is_plugged": top_plugged,
        "fast_connector": fast_connector,
        "slow_connector": slow_connector,
        "connector_known": connector_known,
        "external_power": external_power,
        "regenerating": regenerating,
        "parked": parked,
        "speed_kmh": speed,
        "charge_state": state_text or None,
        "generic_plug_signal_trusted": connector_known or external_power,
    })


def _picture_key(value: Any) -> str | None:
    preferred = {"key", "picturekey", "picture_key", "carpicturekey", "car_picture_key", "packagekey", "package_key", "pickey"}
    if isinstance(value, dict):
        for key, candidate in value.items():
            normalized = re.sub(r"[^a-z0-9_]", "", str(key).lower())
            if normalized in preferred and isinstance(candidate, (str, int)):
                text = str(candidate).strip()
                if 8 <= len(text) <= 1000:
                    return text
        for candidate in value.values():
            found = _picture_key(candidate)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for candidate in value:
            found = _picture_key(candidate)
            if found:
                return found
    return None


def _validate_picture_zip(raw: bytes) -> None:
    if len(raw) < 512 or len(raw) > 25 * 1024 * 1024:
        raise ValueError("Pacote oficial de imagens fora do limite permitido.")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 160:
            raise ValueError("Pacote oficial de imagens possui arquivos demais.")
        total = 0
        for entry in entries:
            total += max(0, int(entry.file_size))
            if entry.file_size > 20 * 1024 * 1024 or total > 120 * 1024 * 1024:
                raise ValueError("Pacote oficial de imagens descompactado excede o limite.")


def _official_picture_package(
    client: Any,
    vehicle: Any,
    remote_id: str,
    force_refresh: bool = False,
    manual_should_yield: Callable[[], bool] | None = None,
    allow_network: bool = True,
) -> tuple[Any, str, Path] | None:
    cache_key = hashlib.sha256(remote_id.encode("utf-8", "ignore")).hexdigest()
    cached = _IMAGE_PACKAGE_CACHE.get(cache_key)
    now = time.time()
    if force_refresh:
        _IMAGE_PACKAGE_CACHE.pop(cache_key, None)
        cached = None
    if cached and now - cached[0] < 6 * 3600:
        return cached[1], cached[2], cached[3]
    root = Path(os.environ.get("LEAPHUB_VEHICLE_IMAGE_DIR", "/data/runtime/vehicle-pictures"))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    package_file = root / f"{cache_key}.zip"
    metadata_file = root / f"{cache_key}.json"
    old_meta: dict[str, Any] = {}
    try:
        if metadata_file.is_file():
            decoded = json.loads(metadata_file.read_text(encoding="utf-8"))
            old_meta = decoded if isinstance(decoded, dict) else {}
    except Exception:
        old_meta = {}

    picture_key: str | None = None
    raw: bytes | None = None
    # 1.12.84 — a telemetria FAST pode recompor a figura usando o pacote já
    # salvo, mas nunca abre metadados/download de imagem enquanto possui a conta.
    # O download binário usa timeout por inatividade, não prazo total, e foi o
    # último caminho capaz de manter o account lock por dezenas de segundos.
    should_refresh = bool(allow_network) and (force_refresh or not package_file.is_file() or now - package_file.stat().st_mtime > 24 * 3600)
    # 1.12.28 — imagem oficial é trabalho secundário. Se um comando manual
    # chegou depois de a leitura de status começar, não abra uma nova chamada
    # de rede para metadados/imagem: use o cache existente e libere a conta.
    try:
        manual_pending = bool(manual_should_yield and manual_should_yield())
    except Exception:
        manual_pending = False
    if manual_pending:
        should_refresh = False
    if should_refresh:
        try:
            metadata = client.get_car_picture(vehicle)
            picture_key = _picture_key(metadata)
            try:
                manual_pending = bool(manual_should_yield and manual_should_yield())
            except Exception:
                manual_pending = False
            if picture_key and not manual_pending:
                raw = client.download_car_picture_package(picture_key=picture_key)
                _validate_picture_zip(raw)
                temporary = package_file.with_suffix(f".tmp-{os.getpid()}")
                temporary.write_bytes(raw)
                os.chmod(temporary, 0o600)
                temporary.replace(package_file)
                metadata_file.write_text(json.dumps({
                    "picture_key_hash": hashlib.sha256(picture_key.encode("utf-8")).hexdigest(),
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                }, separators=(",", ":")), encoding="utf-8")
                os.chmod(metadata_file, 0o600)
        except Exception as exc:
            print(f"Leap Hub: imagem oficial indisponível nesta leitura ({type(exc).__name__}).", file=sys.stderr)

    if not package_file.is_file():
        return None
    try:
        raw = package_file.read_bytes()
        _validate_picture_zip(raw)
        package = _LazyOfficialImagePackage.from_zip(raw)
        key_hash = str(old_meta.get("picture_key_hash") or "")
        if picture_key:
            key_hash = hashlib.sha256(picture_key.encode("utf-8")).hexdigest()
        _IMAGE_PACKAGE_CACHE[cache_key] = (now, package, key_hash, package_file)
        return package, key_hash, package_file
    except Exception as exc:
        print(f"Leap Hub: pacote oficial de imagem inválido ({type(exc).__name__}).", file=sys.stderr)
        return None


def _official_render_cache_key(remote_id: str, picture_key_hash: str, render_layer_signature: str) -> str:
    source = "|".join([
        str(remote_id or "").strip(),
        str(picture_key_hash or "").strip().lower(),
        str(render_layer_signature or "parked").strip().lower(),
        f"contract-{IMAGE_RENDER_CONTRACT_VERSION}",
    ])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _official_render_cache_get(cache_key: str) -> tuple[bytes, str, dict[str, Any]] | None:
    cached = _IMAGE_RENDER_CACHE.get(cache_key)
    if cached is None:
        return None
    stored_at, image_bytes, sha256, cleanup = cached
    if time.time() - stored_at > 6 * 3600:
        _IMAGE_RENDER_CACHE.pop(cache_key, None)
        return None
    return image_bytes, sha256, dict(cleanup)


def _official_render_cache_put(cache_key: str, image_bytes: bytes, sha256: str, cleanup: dict[str, Any]) -> None:
    _IMAGE_RENDER_CACHE[cache_key] = (time.time(), image_bytes, sha256, dict(cleanup))
    if len(_IMAGE_RENDER_CACHE) <= 32:
        return
    for key, _value in sorted(_IMAGE_RENDER_CACHE.items(), key=lambda item: item[1][0])[: len(_IMAGE_RENDER_CACHE) - 24]:
        _IMAGE_RENDER_CACHE.pop(key, None)


def official_visual_image_payload(
    client: Any,
    vehicle: Any,
    status: Any,
    remote_id: str,
    visual_fingerprint_value: str,
    visual_signature: str,
    visual_primary_state: str,
    visual_components: list[str],
    evidence: dict[str, Any],
    captured_at: str,
    force_visual_bytes: bool = False,
    force_debug_package: bool = False,
    force_package_refresh: bool = False,
    manual_should_yield: Callable[[], bool] | None = None,
    allow_network: bool = True,
) -> dict[str, Any] | None:
    total_started = time.monotonic()
    package_started = total_started
    package_cache_key = hashlib.sha256(str(remote_id or "").encode("utf-8", "ignore")).hexdigest()
    package_cache_hit = package_cache_key in _IMAGE_PACKAGE_CACHE
    resolved = _official_picture_package(
        client,
        vehicle,
        remote_id,
        force_refresh=force_package_refresh,
        manual_should_yield=manual_should_yield,
        allow_network=allow_network,
    )
    if resolved is None:
        return None
    package, picture_key_hash, package_file = resolved
    package_ms = int(round((time.monotonic() - package_started) * 1000))
    try:
        render_state, render_components, render_layer_signature = _official_render_contract(
            visual_components,
            evidence,
        )
        cache_key = _official_render_cache_key(remote_id, picture_key_hash, render_layer_signature)
        cached_render = None if force_package_refresh else _official_render_cache_get(cache_key)
        state_cache_hit = cached_render is not None
        visual_status = _official_visual_status(render_components, render_state)
        render_started = time.monotonic()
        if cached_render is not None:
            image_bytes, sha256, cleanup = cached_render
        else:
            image_bytes, output_mime, cleanup = _compose_official_output(package, visual_status, render_state)
            sha256 = hashlib.sha256(image_bytes).hexdigest()
            _official_render_cache_put(cache_key, image_bytes, sha256, cleanup)
        render_ms = int(round((time.monotonic() - render_started) * 1000))
        changed = force_visual_bytes or _IMAGE_LAST_HASH.get(remote_id) != sha256
        _IMAGE_LAST_HASH[remote_id] = sha256
        rendered_components = sorted({
            str(component).strip().lower()
            for component in visual_components
            if re.fullmatch(r"[a-z0-9-]{1,80}", str(component).strip().lower())
        })[:64]
        rendered_state = str(visual_primary_state or "parked").strip().lower()
        if rendered_state not in {"parked", "unlocked", "driving", "plugged", "charging"}:
            rendered_state = "parked"
        consistency_source = json.dumps({
            "sha256": sha256,
            "state": rendered_state,
            "signature": visual_signature,
            "components": rendered_components,
            "fingerprint": visual_fingerprint_value,
            "layer_signature": render_layer_signature,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        payload = {
            "source": "leapmotor-picture-package",
            "available": True,
            "mime": "image/webp",
            "sha256": sha256,
            "visual_fingerprint": visual_fingerprint_value,
            "visual_signature": visual_signature,
            "rendered_primary_state": rendered_state,
            "rendered_signature": visual_signature,
            "rendered_components": rendered_components,
            "rendered_layer_state": render_state,
            "rendered_layer_signature": render_layer_signature,
            "rendered_layer_components": render_components,
            "image_cleanup": cleanup,
            "render_contract_version": IMAGE_RENDER_CONTRACT_VERSION,
            "visual_image_state_key": cache_key,
            "state_cache_hit": state_cache_hit,
            "consistency_hash": hashlib.sha256(consistency_source.encode("utf-8")).hexdigest(),
            "picture_key_hash": picture_key_hash if re.fullmatch(r"[a-f0-9]{64}", picture_key_hash or "") else None,
            "captured_at": captured_at,
        }
        # Reenvia os bytes apenas quando a composição mudou. Os metadados ficam
        # disponíveis em todos os ciclos, sem transformar uma imagem já salva
        # em "indisponível" só porque ela foi deduplicada.
        base64_started = time.monotonic()
        if changed:
            payload["data_base64"] = base64.b64encode(image_bytes).decode("ascii")
        base64_ms = int(round((time.monotonic() - base64_started) * 1000))
        # 1.12.94 — a galeria de diagnóstico é pesada: ela recompõe a figura
        # e converte várias camadas para WebP. Telemetria normal nunca precisa
        # desse material; só uma solicitação explícita de diagnóstico o gera.
        if force_debug_package:
            debug_payload = _official_debug_payload(
                remote_id, package_file, package, visual_status, picture_key_hash,
                render_layer_signature, render_components, captured_at,
                force=True,
            )
            if debug_payload is not None:
                payload["debug_package"] = debug_payload
        total_ms = int(round((time.monotonic() - total_started) * 1000))
        if total_ms >= 100:
            connector_log(
                logging.INFO,
                "Imagem local de %s: pacote=%sms cache_pacote=%s render=%sms cache_estado=%s base64=%sms total=%sms camadas_decodificadas=%s.",
                str(remote_id or "")[-5:],
                package_ms,
                package_cache_hit,
                render_ms,
                state_cache_hit,
                base64_ms,
                total_ms,
                int(getattr(package, "decoded_layer_count", 0) or 0),
            )
        return payload
    except Exception as exc:
        print(f"Leap Hub: composição da imagem oficial falhou ({type(exc).__name__}).", file=sys.stderr)
        return None


def _remember_official_visual_metadata(remote_id: str, payload: dict[str, Any]) -> None:
    """Cache only safe render metadata for later state-only telemetry."""
    key = str(remote_id or "").strip()
    signature = str(payload.get("rendered_signature") or payload.get("visual_signature") or "").strip()
    if not key or not signature:
        return
    metadata = {
        name: value
        for name, value in payload.items()
        if name not in {"data_base64", "debug_package"}
    }
    metadata["_cache_signature"] = signature
    _IMAGE_METADATA_CACHE[key] = metadata
    if len(_IMAGE_METADATA_CACHE) > 64:
        for stale_key in list(_IMAGE_METADATA_CACHE)[:-48]:
            _IMAGE_METADATA_CACHE.pop(stale_key, None)


def cached_official_visual_metadata(remote_id: str, visual_signature: str) -> dict[str, Any] | None:
    """Return metadata only when it still represents the same visual state."""
    key = str(remote_id or "").strip()
    signature = str(visual_signature or "").strip()
    cached = _IMAGE_METADATA_CACHE.get(key)
    if not isinstance(cached, dict) or cached.get("_cache_signature") != signature:
        return None
    return {name: value for name, value in cached.items() if name != "_cache_signature"}


def render_official_visual_snapshot(vehicle_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Render from immutable telemetry + local ZIP, with no cloud capability.

    This API intentionally accepts no Leapmotor client, token, credentials,
    session, command callback or dispatch function. `allow_network=False` is a
    structural guard: a slow image can never own the vehicle account.
    """
    if not isinstance(vehicle_snapshot, dict):
        return None
    rendered = json.loads(json.dumps(vehicle_snapshot, ensure_ascii=False, default=json_default))
    telemetry = rendered.get("telemetry") if isinstance(rendered.get("telemetry"), dict) else {}
    remote_id = str(rendered.get("remote_id") or "").strip()
    visual_signature = str(telemetry.get("visual_signature") or "").strip()
    if not remote_id or not visual_signature:
        return None

    image = official_visual_image_payload(
        None,
        None,
        None,
        remote_id,
        str(telemetry.get("visual_fingerprint") or ""),
        visual_signature,
        str(telemetry.get("visual_primary_state") or "parked"),
        list(telemetry.get("visual_components") or []),
        dict(telemetry.get("charging_evidence") or {}),
        str(telemetry.get("captured_at") or datetime.utcnow().isoformat() + "Z"),
        force_visual_bytes=True,
        force_debug_package=False,
        force_package_refresh=False,
        manual_should_yield=None,
        allow_network=False,
    )
    if image is None:
        return None

    telemetry["visual_image"] = image
    telemetry["official_visual_image"] = {
        name: value for name, value in image.items() if name != "data_base64"
    }
    rendered["telemetry"] = telemetry
    _remember_official_visual_metadata(remote_id, image)
    _IMAGE_LAST_SIGNATURE[remote_id] = visual_signature
    return rendered


def charging_label(status: Any) -> str:
    return str(charging_evidence(status).get("state") or "not_charging")

def serialize_vehicle(
    vehicle: Any,
    include_status: bool,
    client: Any,
    messages: list[Any] | None = None,
    allow_unscoped_messages: bool = False,
    force_visual_bytes: bool = False,
    force_debug_package: bool = False,
    force_package_refresh: bool = False,
    manual_should_yield: Callable[[], bool] | None = None,
    include_secondary_network: bool = True,
    status_override: Any | None = None,
    include_official_image: bool = True,
) -> dict[str, Any]:
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

    def capability_label(item: Any) -> str:
        parts: list[str] = []
        for candidate in (
            value_of(item),
            attribute(item, "name"),
            attribute(item, "description"),
            str(item),
        ):
            value = " ".join(str(candidate or "").split()).strip()
            if value and value not in parts:
                parts.append(value[:120])
        return " | ".join(parts)[:240]

    abilities = [label for item in raw_abilities if (label := capability_label(item))]
    rights = [label for item in raw_rights if (label := capability_label(item))]
    module_rights = [label for item in raw_module_rights if (label := capability_label(item))]
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
    # Matriz ciente da capacidade do veículo: um comando só é anunciado se a
    # biblioteca o implementa E o carro possui o direito correspondente. Sem dados
    # de capacidade, o filtro é fail-open (ver command_permitted_by_vehicle).
    vehicle_right_codes = effective_right_codes(raw_rights, raw_abilities)
    supported_commands = [
        key for key, method in COMMAND_METHODS.items()
        if callable(getattr(client, method, None))
        and command_permitted_by_vehicle(key, vehicle_right_codes)
    ]
    experimental_commands = [
        key for key, method in EXPERIMENTAL_COMMAND_METHODS.items()
        if callable(getattr(client, method, None))
        and command_permitted_by_vehicle(key, vehicle_right_codes)
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
            "experimental_commands": experimental_commands,
        },
    }
    if not include_status:
        return result

    # 1.12.88 — a telemetria pode fornecer o VehicleStatus já obtido
    # por uma chamada one-shot controlada. Todos os demais chamadores
    # continuam usando o método público exatamente como antes.
    status = status_override if status_override is not None else client.get_vehicle_status(vehicle)
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

    tire_data, tire_temperature_data = tire_metrics(tires, status)

    speed_value = numeric(attribute(driving, "speed"))
    parked_value = bool_or_none(attribute(status, "is_parked")) if attribute(status, "is_parked") is not None else bool_or_none(attribute(driving, "is_parked"))
    ready_value = bool_or_none(attribute(driving, "ready")) if attribute(driving, "ready") is not None else bool_or_none(attribute(status, "ready"))
    ignition_value = bool_or_none(attribute(driving, "vehicle_on")) if attribute(driving, "vehicle_on") is not None else bool_or_none(attribute(status, "is_on"))
    charging_evidence_data = charging_evidence(status)
    charging_state = str(charging_evidence_data.get("state") or "not_charging")
    plugged_value = bool_or_none(charging_evidence_data.get("plugged"))
    regenerating_value = bool_or_none(charging_evidence_data.get("regenerating"))
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
        "front_left": effective_window_open(window_positions["front_left"], attribute(windows, "driver_window_status")),
        "front_right": effective_window_open(window_positions["front_right"], attribute(windows, "right_front_window_status")),
        "rear_left": effective_window_open(window_positions["rear_left"], attribute(windows, "left_rear_window_status")),
        "rear_right": effective_window_open(window_positions["rear_right"], attribute(windows, "right_rear_window_status")),
    }

    raw_window_signals = safe_window_raw_signals(attribute(status, "raw"))
    log_window_telemetry_diag(window_positions, window_state, raw_window_signals)

    # 1.12.105: probe no mesmo ponto comprovado pelas janelas.
    raw_climate_probe = safe_climate_comfort_raw_signals(attribute(status, "raw"))
    log_climate_comfort_raw_probe(raw_climate_probe)

    roof_opening = first_numeric(attribute(security, "roof_opening"), map_numeric(cloud_scalars, "roofOpening", "sunroofOpening", "roofOpenPercent"))
    sunshade_position = first_numeric(attribute(windows, "sun_shade"), map_numeric(cloud_scalars, "sunShade", "sunshadeOpening", "sunshadePercent"))
    # 1.12.63 — no C10 e no B10 o vidro do teto é fixo: o único motor é o da
    # cortina. É o estado dela que a nuvem publica no signal 1724, que a
    # `leapmotor_api` entrega como `security.roof_opening`. Medido nos dois
    # sentidos em 30/07/2026, no carro do proprietário: cortina aberta -> 100,
    # cortina fechada -> 0, enquanto `sun_shade` e `sunshadeOpening` nunca vieram
    # preenchidos.
    #
    # Sem esta troca três coisas ficam erradas de uma vez: a figura do carro
    # acende o selo do teto solar quando a cortina abre, `sunshade_open` fica
    # nulo para sempre, e o matcher de `sunshade_open`/`sunshade_close` não tem o
    # que ler — o comando executa no carro e a tela nunca conclui.
    #
    # A troca é condicionada ao modelo de propósito: `rightList` declara o
    # direito 160 (teto solar) mesmo nesses carros, ou seja, o direito não prova
    # o mecanismo. Um modelo com teto deslizante de verdade continua no caminho
    # de cima, e um carro que publique os dois campos também.
    if (
        sunshade_position is None
        and roof_opening is not None
        and visual_model_family(model) in {"c10", "b10"}
    ):
        sunshade_position = roof_opening
        roof_opening = None
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
        # 1.12.90 — sinal térmico alternativo presente em alguns modelos/firmwares.
        # Não cria nova chamada: apenas serializa o que já veio no mesmo status.
        "cooling_and_heating": enum_or_value(attribute(climate, "ac_cooling_and_heating")),
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
    # 1.12.106 - hotfix: climate_state e seat_state precisam existir antes
    # do diagnostico tipado. Isso restaura a conclusao de serialize_vehicle()
    # e, consequentemente, collection_total + fila/entrega de telemetria.
    raw_climate_comfort_signals = safe_climate_comfort_raw_signals(attribute(status, "raw"))
    log_climate_comfort_diag(climate_state, seat_state, mirrors_state, raw_climate_comfort_signals)

    charge_plan = attribute(battery, "charge_plan")
    charge_state_details = compact_mapping({
        "remaining_minutes": first_numeric(attribute(battery, "charge_remain_time")),
        "fast_connector": bool_or_none(charging_evidence_data.get("fast_connector")),
        "slow_connector": bool_or_none(charging_evidence_data.get("slow_connector")),
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
        "version": 9,
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
        "charging_evidence": charging_evidence_data,
        "tire_status": tire_states,
        "ignition_details": ignition_state,
        "vehicle_image_url": vehicle_image_url,
        "exterior_color": exterior_color,
        "visual_state_version": 9,
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
            "version": 9,
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
        "tire_data": tire_data,
        "tire_temperature_data": tire_temperature_data,
        "captured_at": captured_at,
        "cloud_raw_redacted": redacted_cloud_raw({
            "vehicle": attribute(vehicle, "raw", {}),
            "status": attribute(status, "raw", {}),
        }),
        "mapping_version": "1.11.75",
    }
    # 1.12.28 — o status do veículo é a parte essencial da telemetria.
    # Metadados/pacote de imagem são secundários e não podem manter a conta
    # ocupada quando um comando manual já está aguardando.
    # 1.12.40 — quando a assinatura visual MUDA, o desenho deixa de ser
    # secundário.
    #
    # Relato do proprietário em 01/08/2026: "a imagem não atualiza em tempo
    # real, tenho que enviar um comando para ela atualizar". O estado chegava na
    # hora — o site mostrava `doors_open: 2` e os marcadores certos — e só o
    # desenho ficava para trás: a leitura FAST adia a imagem SEMPRE, e os bytes
    # só saem com `force_visual_bytes`, que hoje é exclusivo do `sync`.
    #
    # Quando a assinatura muda (`unlocked--trunk-open` para
    # `unlocked--front-left-open--rear-left-open`), a composição anterior deixou
    # de descrever o veículo. Aí ela não é mais um extra: é a única coisa errada
    # na tela.
    #
    # O comando manual continua com prioridade absoluta — `manual_waiting` segue
    # adiando, que é a garantia da 1.12.28. O custo é uma composição por MUDANÇA
    # de estado, não por leitura, e `_official_render_cache_key()` já evita
    # recompor estado repetido.
    visual_key = remote_id or vin

    # 1.12.94 — a telemetria essencial termina antes de Pillow/ZIP/WebP.
    # Se a figura já foi renderizada para a MESMA assinatura, reaproveitamos
    # só os metadados baratos para manter deduplicação estável. Se mudou, o
    # worker visual anexará os bytes depois, já fora de qualquer trava cloud.
    if not include_official_image:
        cached_visual = cached_official_visual_metadata(visual_key, visual_signature)
        if cached_visual is not None:
            telemetry["visual_image"] = dict(cached_visual)
            telemetry["official_visual_image"] = dict(cached_visual)
        else:
            telemetry["official_visual_image"] = compact_mapping({
                "source": "leapmotor-picture-package",
                "available": False,
                "deferred_local_render": True,
                "visual_fingerprint": visual_fingerprint_value,
                "rendered_primary_state": visual_primary_state,
                "rendered_signature": visual_signature,
                "render_contract_version": IMAGE_RENDER_CONTRACT_VERSION,
            })
        result["telemetry"] = telemetry
        return result

    try:
        manual_waiting = bool(manual_should_yield and manual_should_yield())
    except Exception:
        manual_waiting = False
    signature_changed = bool(visual_signature) and _IMAGE_LAST_SIGNATURE.get(visual_key) != visual_signature
    defer_secondary_network = should_defer_official_image(
        include_secondary_network=include_secondary_network,
        manual_waiting=manual_waiting,
        signature_changed=signature_changed,
    )
    if defer_secondary_network:
        connector_log(logging.DEBUG, "Telemetria adiou imagem oficial pelo perfil FAST ou para liberar a conta a um comando manual.")
        official_image = None
    else:
        official_image = official_visual_image_payload(
            client,
            vehicle,
            status,
            remote_id or vin,
            visual_fingerprint_value,
            visual_signature,
            visual_primary_state,
            visual_components,
            charging_evidence_data,
            captured_at,
            # Assinatura nova exige os BYTES: só metadados fariam o site manter
            # o desenho antigo, que é exatamente o defeito relatado.
            force_visual_bytes=force_visual_bytes or signature_changed,
            force_debug_package=force_debug_package,
            force_package_refresh=force_package_refresh,
            manual_should_yield=manual_should_yield,
            allow_network=include_secondary_network,
        )
        if official_image is not None and visual_signature:
            _IMAGE_LAST_SIGNATURE[visual_key] = visual_signature
            if len(_IMAGE_LAST_SIGNATURE) > 64:
                for stale_key in list(_IMAGE_LAST_SIGNATURE)[:-64]:
                    _IMAGE_LAST_SIGNATURE.pop(stale_key, None)
    if official_image is not None:
        # visual_image sem data_base64 funciona como heartbeat de metadados; o
        # site mantém o último arquivo oficial persistido.
        telemetry["visual_image"] = official_image
        telemetry["official_visual_image"] = {
            key: value for key, value in official_image.items() if key != "data_base64"
        }
    else:
        telemetry["official_visual_image"] = compact_mapping({
            "source": "leapmotor-picture-package",
            "available": False,
            "visual_fingerprint": visual_fingerprint_value,
            "rendered_primary_state": visual_primary_state,
            "rendered_signature": visual_signature,
            "render_contract_version": IMAGE_RENDER_CONTRACT_VERSION,
        })
    result["telemetry"] = telemetry
    return result


def create_client(credentials: dict[str, Any], temp_dir: Path, operation_password: str | None = None, request_timeout_seconds: int = 35) -> Any:
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
        timeout=max(12, min(45, int(request_timeout_seconds))),
        verify_ssl=strict_tls,
        language="en-GB",
    )


# ----------------------------------------------------------------------------
# 1.12.72 — leitura de DIAGNÓSTICO do histórico da nuvem.
#
# Por que existe: a telemetria ao vivo só enxerga o que o carro subiu, e o carro
# para de subir enquanto roda. Medido em 31/07/2026 numa viagem de 94 km: das
# 112 leituras, 72 eram a MESMA — o Gateway perguntou 72 vezes durante 71
# minutos e a nuvem devolveu sempre o mesmo instantâneo, enquanto 60 km eram
# percorridos. O trecho de rodovia simplesmente não existe na telemetria.
#
# A `leapmotor-api` expõe quatro leituras de HISTÓRICO que este conector nunca
# chamou, e uma delas é `/carownerservice/oversea/drivingRecord/v1/mileage/
# energy/detail` — o registro de condução do próprio carro, que não depende da
# nossa cadência.
#
# Esta função NÃO consome nada. Ela chama, mede a FORMA da resposta e devolve o
# esqueleto (chaves, tipos, tamanhos, uma amostra recortada). É deliberado: a
# decisão do wakeUp na 1.12.70 quase virou código inerte por ser escrita antes
# de alguém olhar o que a biblioteca oferecia. Primeiro se mede, depois se
# escreve o consumidor.
# ----------------------------------------------------------------------------
DRIVING_RECORD_METHODS = (
    "get_mileage_energy_detail",
    "get_consumption_last_week_breakdown",
    "get_consumption_weekly_rank",
    "get_charging_daily_detail",
)

# Nada de valor bruto num diagnóstico: só forma. Um número vira o seu tipo e a
# sua ordem de grandeza; um texto vira o seu tamanho. O que interessa aqui é
# saber QUAIS campos existem, não quanto o dono rodou.
def describe_shape(value: Any, depth: int = 0, max_depth: int = 4) -> Any:
    if depth >= max_depth:
        return type(value).__name__ + " (profundidade cortada)"
    if isinstance(value, dict):
        return {str(k)[:60]: describe_shape(v, depth + 1, max_depth) for k, v in list(value.items())[:60]}
    if isinstance(value, (list, tuple)):
        if not value:
            return "lista vazia"
        return {
            "lista": len(value),
            "primeiro_item": describe_shape(value[0], depth + 1, max_depth),
        }
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return f"int (~1e{len(str(abs(value))) - 1})" if value else "int (0)"
    if isinstance(value, float):
        return f"float (~1e{len(str(int(abs(value)))) - 1})" if value else "float (0)"
    if value is None:
        return "nulo"
    if isinstance(value, str):
        return f"texto[{len(value)}]"
    return type(value).__name__


def handle_driving_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Chama as leituras de histórico e devolve só a FORMA do que voltou."""
    credentials = payload.get("credentials") if isinstance(payload.get("credentials"), dict) else {}
    vehicle_id = str(payload.get("vehicle_id") or "").strip()
    temp_dir = secure_temp_directory()
    resultados: list[dict[str, Any]] = []
    try:
        client = create_client(credentials, temp_dir / "attempt-1", None, request_timeout_seconds=32)
        try:
            client.login()
            vehicles = list(client.get_vehicle_list() or [])
            if not vehicles:
                return {"ok": False, "message": "A conta não retornou nenhum veículo."}
            selected = vehicles[0]
            if vehicle_id:
                for item in vehicles:
                    if vehicle_id in {
                        str(attribute(item, "vin", "") or ""),
                        str(attribute(item, "car_id", "") or ""),
                    }:
                        selected = item
                        break
            for nome in DRIVING_RECORD_METHODS:
                metodo = getattr(client, nome, None)
                if not callable(metodo):
                    resultados.append({"metodo": nome, "existe": False})
                    continue
                started = time.monotonic()
                try:
                    try:
                        bruto = metodo(selected)
                    except TypeError:
                        bruto = metodo()
                    resultados.append({
                        "metodo": nome,
                        "existe": True,
                        "ok": True,
                        "duracao_ms": int(round((time.monotonic() - started) * 1000)),
                        "tipo": type(bruto).__name__,
                        "forma": describe_shape(
                            bruto if isinstance(bruto, (dict, list)) else getattr(bruto, "__dict__", bruto)
                        ),
                    })
                except Exception as exc:  # noqa: BLE001
                    # Uma leitura que falha não pode derrubar as outras: é
                    # justamente saber QUAIS respondem que este diagnóstico
                    # existe para descobrir.
                    resultados.append({
                        "metodo": nome,
                        "existe": True,
                        "ok": False,
                        "duracao_ms": int(round((time.monotonic() - started) * 1000)),
                        "erro": clean_message(str(exc))[:300],
                    })
        finally:
            try:
                client.close()
            except Exception:
                pass
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return {
        "ok": True,
        "connector_version": CONNECTOR_VERSION,
        "library_version": package_version(),
        "leituras": resultados,
        "aviso": "Diagnóstico: só a forma da resposta, sem valores. Nada foi consumido.",
    }


def handle_account(
    payload: dict[str, Any],
    sync: bool,
    borrowed_client: Any | None = None,
    borrowed_vehicles: list[Any] | None = None,
) -> dict[str, Any]:
    credentials_value = payload.get("credentials") if sync else payload
    credentials = credentials_value if isinstance(credentials_value, dict) else {}
    vehicle_id = str(payload.get("vehicle_id") or "").strip() if sync else ""
    force_visual_bytes = bool(payload.get("force_visual_bytes")) if sync else False
    force_debug_package = bool(payload.get("force_debug_package")) if sync else False
    force_package_refresh = bool(payload.get("force_package_refresh")) if sync else False
    client = borrowed_client
    client_is_borrowed = borrowed_client is not None
    temp_dir: Path | None = None
    try:
        try:
            if client is None:
                temp_dir = secure_temp_directory()
                attempt_dir = temp_dir / "attempt-1"
                attempt_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
                client = create_client(credentials, attempt_dir, None)
                # Uma solicitação gera no máximo um login. Falhas transitórias são
                # devolvidas ao coordenador global, que persiste o próximo prazo.
                client.login()
                vehicles_value = client.get_vehicle_list()
                vehicles = vehicles_value if isinstance(vehicles_value, list) else list(vehicles_value or [])
            else:
                vehicles = list(borrowed_vehicles) if isinstance(borrowed_vehicles, list) and borrowed_vehicles else []
                if not vehicles:
                    vehicles_value = client.get_vehicle_list()
                    vehicles = vehicles_value if isinstance(vehicles_value, list) else list(vehicles_value or [])
        except Exception as exc:  # noqa: BLE001
            cooldown = login_cooldown_seconds(exc)
            if cooldown > 0:
                raise ConnectorLoginCooldownError(
                    "A Leapmotor limitou temporariamente novas autenticações. A solicitação continuará protegida até a próxima tentativa permitida.",
                    cooldown,
                ) from exc
            if is_transient_cloud_error(exc):
                raise ConnectorTemporaryError(reconnect_message(exc)) from exc
            if is_authentication_error(exc):
                raise ConnectorAuthenticationError(
                    "A sessão ou a conta Leapmotor recusou a autenticação. "
                    "Nenhuma repetição paralela será iniciada."
                ) from exc
            raise RuntimeError(clean_message(str(exc))) from exc

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
                include_status=sync,
                client=client,
                messages=messages,
                allow_unscoped_messages=len(selected) == 1,
                force_visual_bytes=force_visual_bytes,
                force_debug_package=force_debug_package,
                force_package_refresh=force_package_refresh,
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
            "login_attempts": 0 if client_is_borrowed else 1,
            "reconnected": False,
            "session_reused": client_is_borrowed,
        }
    finally:
        if client is not None and not client_is_borrowed:
            try:
                client.close()
            except Exception:
                pass
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)



VEHICLE_SLEEP_MARKERS = (
    "vehicle asleep", "vehicle is asleep", "car asleep", "car is asleep",
    "sleeping", "deep sleep", "vehicle offline", "car offline",
    "not awake", "not ready", "vehicle unavailable", "car unavailable",
    "wake up vehicle", "wake vehicle", "please wake", "dormindo",
    "veículo offline", "veiculo offline", "não está pronto", "nao esta pronto",
)


def is_vehicle_sleep_error(value: Any) -> bool:
    message = clean_message(str(value)).lower()
    return any(marker in message for marker in VEHICLE_SLEEP_MARKERS)


def is_remote_command_confirmation_timeout(value: Any) -> bool:
    """The cloud accepted the command but the library did not receive final confirmation.

    leapmotor-api raises this only after /remote/ctl returned a remoteCtlId and
    the subsequent result polling exceeded its deadline. Re-sending the command
    would be unsafe; the telemetry confirmation window must resolve the state.
    """
    message = clean_message(str(value)).lower()
    return "timed out waiting for remote control result" in message


def is_remote_command_result_session_error(value: Any) -> bool:
    """The write endpoint accepted the command, but result polling lost its token.

    This is not a safe reason to resend the command because the cloud already
    returned a remoteCtlId. The telemetry window must confirm the final state.
    """
    message = clean_message(str(value)).lower()
    return any(marker in message for marker in (
        "remote control result failed: token is invalid",
        "remote control result failed: invalid token",
        "remote control result failed: token expired",
        "remote control result failed: session expired",
    ))


def try_wake_vehicle(client: Any, vehicle_id: str) -> dict[str, Any]:
    """Use an explicit wake primitive when the installed library exposes one.

    Different releases of leapmotor-api used different method names. Reflection
    keeps the connector compatible and never treats absence of a wake method as
    a failure because many command endpoints wake the car themselves.

    MEDIDO em 02/08/2026 contra leapmotor-api 0.3.2, a versão fixada em
    requirements.txt: NENHUM dos nomes abaixo existe no cliente. A biblioteca
    expõe exatamente uma leitura de estado (`vehicle/v1/status/get`, que devolve
    o último instantâneo que o carro subiu) e nenhuma operação de despertar ou
    de forçar atualização. Portanto:

      * esta função devolve `attempted: False` em toda instalação atual, e o
        único chamador trata isso como "não dá para acordar", que é a verdade;
      * "forçar refresh/wakeUp antes de amostrar a confirmação" NÃO é
        implementável com esta biblioteca — seria código inerte. Quem acorda o
        carro é o próprio comando, e a lentidão medida na confirmação vinha do
        backoff da janela, corrigido na 1.12.70 no telemetry_engine.

    Se uma versão futura da biblioteca ganhar a primitiva, ela passa a ser
    encontrada aqui sem mudança nenhuma.
    """
    for method_name in (
        "wake_vehicle", "wake_up_vehicle", "wakeup_vehicle",
        "wake_vehicle_up", "wake_up", "wakeup",
    ):
        method = getattr(client, method_name, None)
        if not callable(method):
            continue
        try:
            try:
                result = method(vehicle_id)
            except TypeError:
                result = method()
            return {"attempted": True, "method": method_name, "result_type": type(result).__name__}
        except Exception as exc:  # noqa: BLE001
            if is_authentication_error(exc):
                raise
            # The cloud may answer that the vehicle is already awake. In that
            # case the command itself is the authoritative next step.
            message = clean_message(str(exc)).lower()
            if any(token in message for token in ("already awake", "already online", "já está acordado", "ja esta acordado")):
                return {"attempted": True, "method": method_name, "already_awake": True}
            if is_transient_cloud_error(exc) or is_vehicle_sleep_error(exc):
                return {"attempted": True, "method": method_name, "temporary": True, "message": clean_message(str(exc))}
            return {"attempted": True, "method": method_name, "failed": True, "message": clean_message(str(exc))}
    return {"attempted": False, "method": None}


def resolve_command_vehicle(
    client: Any,
    supplied_identifier: str,
    vin_hint: str = "",
    vehicles_hint: list[Any] | None = None,
) -> tuple[str, list[Any] | None, str]:
    """Resolve o identificador salvo pelo Leap Hub para o VIN exigido pela biblioteca.

    A telemetria usa ``car_id`` como remote_id, enquanto leapmotor-api executa
    comandos exclusivamente pelo VIN. Versões anteriores repassavam car_id como
    se fosse VIN e todos os comandos terminavam em HTTP 422.
    """
    vin_hint = str(vin_hint or "").strip()[:40]
    if vin_hint:
        return vin_hint, list(vehicles_hint) if isinstance(vehicles_hint, list) and vehicles_hint else None, "vin_hint"

    supplied_identifier = str(supplied_identifier or "").strip()[:190]
    # Quando a telemetria já possui uma sessão autenticada, reutilizamos também
    # a última lista válida de veículos. Isso evita destruir um token saudável e
    # refazer vehicle/list imediatamente antes de um comando remoto.
    vehicles = list(vehicles_hint) if isinstance(vehicles_hint, list) and vehicles_hint else list(client.get_vehicle_list() or [])
    selected = None
    source = ""
    for vehicle in vehicles:
        vin = str(attribute(vehicle, "vin", "") or "").strip()
        car_id = str(attribute(vehicle, "car_id", "") or "").strip()
        if supplied_identifier and supplied_identifier == vin:
            selected = vehicle
            source = "vin"
            break
        if supplied_identifier and supplied_identifier == car_id:
            selected = vehicle
            source = "car_id"
            break
    if selected is None and len(vehicles) == 1:
        selected = vehicles[0]
        source = "single_vehicle"
    if selected is None:
        raise RuntimeError("Não foi possível associar o veículo salvo ao VIN da conta Leapmotor. Sincronize a conta e tente novamente.")
    resolved_vin = str(attribute(selected, "vin", "") or "").strip()
    if not resolved_vin:
        raise RuntimeError("A nuvem Leapmotor não retornou o VIN necessário para executar o comando.")
    return resolved_vin, vehicles, source


def climate_auto_parameters(parameters: dict[str, Any]) -> dict[str, str]:
    """Payload AUTO comprovado para a plataforma C10/B10/B05."""
    raw_temperature = parameters.get("target_temperature", 24)
    try:
        temperature = int(round(float(raw_temperature)))
    except (TypeError, ValueError):
        temperature = 24
    temperature = max(18, min(temperature, 32))
    return {
        "circle": "in",
        "mode": "nohotcold",
        "operate": "auto",
        "position": "all",
        "temperature": str(temperature),
        "windlevel": "5",
        "wshld": "0",
    }


def windshield_defrost_parameters() -> dict[str, str]:
    """Payload de desembaçamento dianteiro verificado para cmd_id 170.

    leapmotor-api 0.3.2 usa wshld=1 no preset interno. A referência de payloads
    verificados do protocolo Leapmotor usa wshld=2 para WINDSHIELD DEFROST,
    enquanto QUICK HEAT permanece em wshld=1. Em campo, o C10 do proprietário
    também publicou signal.1945=2 quando o MAX do para-brisa estava ativo.
    """
    return {
        "circle": "in",
        "mode": "hot",
        "operate": "manual",
        "position": "all",
        "temperature": "32",
        "windlevel": "7",
        "wshld": "2",
    }


def execute_vehicle_command(
    method: Any,
    command: str,
    vehicle_id: str,
    parameters: dict[str, Any],
    climate_profile: str = "generic",
    window_native_scale: int = 100,
) -> Any:
    # 1.12.79 — C10/B10/B05: AUTO é um cmd 170 completo e OFF é ac_switch
    # operate=off. O parâmetro climate_profile permanece apenas por compatibilidade
    # de chamada nesta release; ele não participa mais do despacho.
    if command == "climate_on":
        return method(vehicle_id, params=climate_auto_parameters(parameters))
    if command == "climate_off":
        return method(vehicle_id, params={"operate": "off"})
    if command == "windshield_defrost":
        # 1.12.107 — a biblioteca 0.3.2 monta este preset com wshld=1, que no
        # C10 aplicou HOT/32/fan7 sem ativar o estado do para-brisa. O payload
        # verificado do protocolo usa wshld=2. Uma chamada, nenhum retry novo.
        connector_log(
            logging.INFO,
            "CLIMATE_DIAG event=windshield_defrost_dispatch wshld=2 tentativas_fisicas=1",
        )
        return method(vehicle_id, params=windshield_defrost_parameters())
    if command == "set_charge_limit":
        value = int(parameters.get("charge_limit_percent", 80))
        if value < 50 or value > 100 or value % 5 != 0:
            raise ValueError("Limite de carga inválido.")
        return method(vehicle_id, charge_limit_percent=value)
    if command in {"windows_open", "windows_close"} and window_native_scale == 10:
        # 1.12.100 - medido no C10 do proprietario em 16/08/2026:
        # value=0 fecha todas as janelas e value=10 abre ate o fim de curso
        # observado. A biblioteca 0.3.2 usa value=100 como OPEN por padrao;
        # nesse C10 a nuvem aceita 100, mas o carro nao executa.
        native = 10 if command == "windows_open" else 0
        connector_log(
            logging.INFO,
            "WINDOW_DIAG event=dispatch comando=%s pedido_site=%s escala_envio=0-10 valor_nativo=%d tentativas_fisicas=1",
            command,
            "100%" if command == "windows_open" else "0%",
            native,
        )
        return method(vehicle_id, value=str(native))
    if command == "windows_position":
        # A interface continua em 0-100%. C10/B10 usam escrita nativa 0-10;
        # T03 e modelos desconhecidos preservam a escrita anterior 0-100.
        try:
            position = int(parameters.get("window_position", parameters.get("value")))
        except (TypeError, ValueError):
            raise ValueError("Informe a posição da janela.") from None
        if position < 0 or position > 100:
            raise ValueError("Posição de janela inválida.")
        if window_native_scale == 10:
            native = (position + 5) // 10
            connector_log(
                logging.INFO,
                "WINDOW_DIAG event=dispatch comando=windows_position pedido_site=%d%% escala_envio=0-10 valor_nativo=%d tentativas_fisicas=1",
                position,
                native,
            )
            return method(vehicle_id, value=str(native))
        return method(vehicle_id, value=str(position))
    if command == "sunshade_position":
        # A cortina é o único comando desta matriz em que a escala de LEITURA e a
        # de ESCRITA não coincidem, e é por isso que a conversão vive aqui e não
        # em quem chama:
        #   - leitura: `sunshade_percent` sai daqui em 0-100, porque no C10/B10 a
        #     nuvem publica a abertura da cortina em `security.roof_opening`,
        #     percentual medido em campo em 30/07/2026 (aberta=100, fechada=0);
        #   - escrita: `SunshadeValue` documenta 0-10, com OPEN="10" e CLOSE="0",
        #     ou seja 11 degraus de 10%.
        # Receber 0-100 e converter mantém uma escala só na conversa com o site e
        # com o dono — que vê "CORT. 45%" na figura e pediria 45, não 4,5. Mandar
        # 45 no comando seria mandar um valor fora da faixa que a biblioteca
        # declara, e o carro ignora o que não entende sem reclamar.
        try:
            percent = int(parameters.get("sunshade_position", parameters.get("value")))
        except (TypeError, ValueError):
            raise ValueError("Informe a posição da cortina.") from None
        if percent < 0 or percent > 100:
            raise ValueError("Posição de cortina inválida.")
        # Arredondamento ao degrau mais próximo, meio para CIMA: 45% vira 5
        # (50%). `round()` do Python é meio para o PAR — `round(4.5)` dá 4 e
        # `round(5.5)` dá 6 —, o que faria a cortina descer num pedido e subir
        # no outro sem regra visível para quem pediu. O valor que o carro recebe
        # é sempre um dos 11 que ele declara aceitar.
        native = (percent + 5) // 10
        # 1.12.99 — diagnóstico observacional somente. Não altera valor,
        # método, número de transmissões nem política de retry.
        connector_log(
            logging.INFO,
            "SUNSHADE_DIAG event=dispatch pedido_site=%d%% valor_nativo=%d escala_envio=0-10 tentativas_fisicas=1",
            percent,
            native,
        )
        return method(vehicle_id, value=str(native))
    if command == "set_speed_limit":
        try:
            limit = int(parameters.get("speed_limit_kmh", parameters.get("value")))
        except (TypeError, ValueError):
            raise ValueError("Informe o limite de velocidade.") from None
        if limit < 30 or limit > 200:
            raise ValueError("Limite de velocidade inválido.")
        return method(vehicle_id, value=str(limit))
    if command in MEDIA_COMMANDS:
        operation = str(parameters.get("operation") or "").strip().lower()
        if operation not in MEDIA_OPERATIONS:
            raise ValueError("Operação de mídia inválida.")
        return method(vehicle_id, operation=operation)
    if command == "prepare_car":
        return method(vehicle_id, params=prepare_car_parameters(parameters))
    if command in RAW_PAYLOAD_COMMANDS:
        return method(vehicle_id, params=raw_command_payload(command, parameters))
    if command == "rear_seats":
        # A biblioteca envia como {"seatInfo": <texto>} e não documenta o formato.
        # Confere-se o que dá: texto curto, sem controle nem separador estranho.
        seat_info = str(parameters.get("seat_info", parameters.get("seatInfo") or "")).strip()
        if seat_info == "":
            raise ValueError("Informe a configuração dos bancos.")
        if len(seat_info) > 120 or re.search(r"[^A-Za-z0-9_,:;.\-]", seat_info) is not None:
            raise ValueError("Configuração de bancos inválida.")
        return method(vehicle_id, seat_info=seat_info)
    if command in {"fota_download", "fota_install"}:
        return method(vehicle_id, task_id=fota_task_id(parameters))
    if command == "fota_schedule":
        schedule_time = str(parameters.get("schedule_time") or "").strip()
        # A biblioteca repassa o texto como veio; exigir o formato aqui evita
        # descobrir o erro só quando o carro recusar a instalação.
        if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", schedule_time) is None:
            raise ValueError("Informe a data e a hora no formato AAAA-MM-DD HH:MM:SS.")
        try:
            datetime.strptime(schedule_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError("Data ou hora inexistente.") from None
        return method(vehicle_id, task_id=fota_task_id(parameters), schedule_time=schedule_time)
    if command in SEAT_COMFORT_COMMANDS:
        # A biblioteca codifica o par como "posição,nível" (posição 1-6, nível 0-3)
        # e exige os dois por palavra-chave. Recusar fora de faixa aqui evita
        # gastar uma ida à nuvem para o carro rejeitar o comando.
        position_raw = parameters.get("seat_position", parameters.get("position"))
        level_raw = parameters.get("seat_level", parameters.get("level"))
        try:
            position = int(position_raw)
            level = int(level_raw)
        except (TypeError, ValueError):
            raise ValueError("Informe a posição e o nível do assento.") from None
        if position < 1 or position > 6:
            raise ValueError("Posição de assento inválida.")
        if level < 0 or level > 3:
            raise ValueError("Nível de assento inválido.")
        return method(vehicle_id, position=position, level=level)
    if command == "send_destination":
        name = str(parameters.get("name") or "Destino")[:100]
        address = str(parameters.get("address") or "")[:240]
        latitude = float(parameters.get("latitude"))
        longitude = float(parameters.get("longitude"))
        if latitude < -90 or latitude > 90 or longitude < -180 or longitude > 180:
            raise ValueError("Coordenadas inválidas.")
        values = {
            "name": name, "title": name, "poi_name": name, "destination_name": name,
            # A biblioteca 0.3.2 exige address_name (keyword-only e sem valor padrão).
            # Sem esta chave a introspecção abaixo trata o parâmetro como não
            # suportado e o envio de destino falha antes de sair do gateway.
            "address_name": name,
            "address": address, "addr": address,
            "latitude": latitude, "lat": latitude,
            "longitude": longitude, "lon": longitude, "lng": longitude,
        }
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return method(vehicle_id, address=address, latitude=latitude, longitude=longitude)
        positional: list[Any] = [vehicle_id]
        keyword: dict[str, Any] = {}
        exposed = list(signature.parameters.values())
        remaining = exposed[1:] if exposed else []
        accepts_var_keyword = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in remaining)
        for item in remaining:
            if item.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
                continue
            if item.name not in values:
                if item.default is inspect.Parameter.empty:
                    raise RuntimeError("Parâmetro de destino ainda não suportado pela biblioteca: " + item.name)
                continue
            if item.kind == inspect.Parameter.POSITIONAL_ONLY:
                positional.append(values[item.name])
            else:
                keyword[item.name] = values[item.name]
        if accepts_var_keyword:
            keyword.setdefault("address", address)
            keyword.setdefault("latitude", latitude)
            keyword.setdefault("longitude", longitude)
        signature.bind(*positional, **keyword)
        return method(*positional, **keyword)
    return method(vehicle_id)


def _select_command_vehicle(
    client: Any,
    resolved_vehicle_id: str,
    vehicles: list[Any] | None = None,
) -> tuple[Any | None, list[Any]]:
    available = list(vehicles or client.get_vehicle_list() or [])
    selected = None
    for vehicle in available:
        vin = str(attribute(vehicle, "vin", "") or "").strip()
        car_id = str(attribute(vehicle, "car_id", "") or "").strip()
        if resolved_vehicle_id in {vin, car_id}:
            selected = vehicle
            break
    if selected is None and len(available) == 1:
        selected = available[0]
    return selected, available


def window_command_native_scale(vehicle: Any | None) -> int:
    """Escala de escrita do cmd_id=230 sem alterar T03/modelos desconhecidos."""
    if vehicle is None:
        return 100
    parts = [
        str(attribute(vehicle, name) or "").strip().lower()
        for name in ("car_type", "model", "model_name", "series_name")
    ]
    normalized = re.sub(r"[^a-z0-9]+", "", " ".join(parts))
    if "c10" in normalized or "b10" in normalized:
        return 10
    return 100


def _status_capture_epoch(status: Any) -> float:
    for name in ("collect_time", "create_time"):
        value = attribute(status, name)
        if isinstance(value, datetime):
            try:
                return float(value.timestamp())
            except (OverflowError, OSError, ValueError):
                continue
        if isinstance(value, str) and value.strip():
            raw = value.strip().replace("Z", "+00:00")
            try:
                return float(datetime.fromisoformat(raw).timestamp())
            except (TypeError, ValueError, OverflowError, OSError):
                continue
    return 0.0


def climate_mode_from_status(climate: Any) -> str:
    """Return the physical HVAC mode used to confirm C10 climate commands."""
    switch_state = bool_or_none(attribute(climate, "ac_switch"))
    if switch_state is False:
        return "off"
    if switch_state is not True:
        return "unknown"

    if bool_or_none(attribute(climate, "is_windshield_defrost_active")) is True:
        return "defrost"
    windshield = numeric(attribute(climate, "windshield_defrost"))
    if windshield in (1, 2):
        return "defrost"

    mode_number = numeric(attribute(climate, "climate_mode"))
    if mode_number == 0:
        return "auto"
    if mode_number == 1:
        return "cooling"
    if mode_number == 3:
        return "heating"

    direction_number = numeric(attribute(climate, "ac_cooling_and_heating"))
    if direction_number == 1:
        return "cooling"
    if direction_number == 2:
        return "heating"

    text = " ".join(
        str(enum_or_value(value) or "").strip().lower()
        for value in (
            attribute(climate, "climate_mode"),
            attribute(climate, "ac_cooling_and_heating"),
            attribute(climate, "ac_operate_mode"),
        )
    )
    if any(token in text for token in ("auto", "nohotcold", "neutral")):
        return "auto"
    if any(token in text for token in ("fast_cool", "cool", "cold", "resfri")):
        return "cooling"
    if any(token in text for token in ("fast_heat", "heat", "hot", "aquec")):
        return "heating"

    rapid_cooling = bool_or_none(attribute(climate, "rapid_cooling"))
    rapid_heating = bool_or_none(attribute(climate, "rapid_heating"))
    if rapid_cooling is True and rapid_heating is not True:
        return "cooling"
    if rapid_heating is True and rapid_cooling is not True:
        return "heating"
    return "unknown"


def climate_profile_from_status(climate: Any) -> str:
    mode = climate_mode_from_status(climate)
    return mode if mode in {"cooling", "heating"} else "generic"


def expected_climate_mode(command: str) -> str | None:
    return {
        "climate_off": "off",
        "climate_on": "auto",
        "quick_cool": "cooling",
        "quick_heat": "heating",
    }.get(command)



def execute_vehicle_command_ack_first(
    method: Any,
    command: str,
    vehicle_id: str,
    parameters: dict[str, Any],
    climate_profile: str = "generic",
    window_native_scale: int = 100,
) -> tuple[Any, bool]:
    """Dispatch allow-listed commands without waiting for library result polling.

    A escala das janelas e somente um argumento do mesmo despacho. Esta funcao
    nao cria retry e restaura o override de polling antes de devolver a sessao.
    """
    if command not in ACK_FIRST_COMMANDS:
        return execute_vehicle_command(
            method,
            command,
            vehicle_id,
            parameters,
            climate_profile,
            window_native_scale,
        ), False

    owner = getattr(method, "__self__", None)
    poll = getattr(owner, "_poll_remote_control_result", None) if owner is not None else None
    if owner is None or not callable(poll):
        return execute_vehicle_command(
            method,
            command,
            vehicle_id,
            parameters,
            climate_profile,
            window_native_scale,
        ), False

    instance_dict = getattr(owner, "__dict__", None)
    sentinel = object()
    previous_override = (
        instance_dict.get("_poll_remote_control_result", sentinel)
        if isinstance(instance_dict, dict)
        else sentinel
    )

    def deferred_result_poll(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"deferred": True, "confirmation_source": "gateway_fast_telemetry"}

    setattr(owner, "_poll_remote_control_result", deferred_result_poll)
    try:
        result = execute_vehicle_command(
            method,
            command,
            vehicle_id,
            parameters,
            climate_profile,
            window_native_scale,
        )
        return result, True
    finally:
        if previous_override is sentinel:
            try:
                delattr(owner, "_poll_remote_control_result")
            except AttributeError:
                pass
        else:
            setattr(owner, "_poll_remote_control_result", previous_override)


def fota_task_id(parameters: dict[str, Any]) -> int:
    """Identificador da tarefa de atualização, vindo da listagem FOTA da nuvem.

    O gateway ainda não expõe essa listagem, então quem aciona precisa informar o
    número. Conferir aqui evita mandar `task_id=0` para a nuvem e receber de volta
    uma recusa opaca.
    """
    try:
        task_id = int(parameters.get("task_id", parameters.get("taskId")))
    except (TypeError, ValueError):
        raise ValueError("Informe o número da tarefa de atualização.") from None
    if task_id < 1:
        raise ValueError("Número de tarefa de atualização inválido.")
    return task_id


RAW_PAYLOAD_MAX_KEYS = 12
RAW_PAYLOAD_MAX_NESTED_KEYS = 8
RAW_PAYLOAD_MAX_BYTES = 512
RAW_PAYLOAD_MAX_TEXT = 120
RAW_PAYLOAD_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")


def _raw_payload_scalar(value: Any, key: str) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value < -1_000_000 or value > 1_000_000:
            raise ValueError(f"Valor fora da faixa aceita em '{key}'.")
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"Valor numérico inválido em '{key}'.")
        return value
    if isinstance(value, str):
        if len(value) > RAW_PAYLOAD_MAX_TEXT:
            raise ValueError(f"Texto longo demais em '{key}'.")
        return value
    raise ValueError(f"Tipo não aceito em '{key}'.")


def raw_command_payload(command: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Confere a *forma* de um pacote cujo vocabulário não é documentado.

    `seat_adjust` (280) e `piloted_parking` (350) são declarados na biblioteca
    apenas como "the full JSON payload string" — não existe lista de campos para
    validar por significado. Repassar o que o site mandar seria entregar à nuvem
    um pacote que ninguém conferiu, então o que se confere é o que dá para
    conferir sem inventar semântica: precisa ser um objeto, com no máximo
    RAW_PAYLOAD_MAX_KEYS chaves de nome plausível, valores escalares (ou um único
    nível de objeto), e tamanho total limitado.

    Isto **não** valida se o comando faz sentido para o carro — só garante que o
    gateway não vira um túnel para conteúdo arbitrário. É a razão de estes dois
    comandos exigirem liberação por proprietário e confirmação explícita.
    """
    raw = parameters.get("payload", parameters.get("params"))
    if isinstance(raw, str):
        text = raw.strip()
        if text == "":
            raise ValueError("Informe os dados do comando.")
        try:
            raw = json.loads(text)
        except (ValueError, TypeError):
            raise ValueError("Os dados do comando não são um JSON válido.") from None
    if not isinstance(raw, dict):
        raise ValueError("Os dados do comando precisam ser um objeto.")
    if raw == {}:
        raise ValueError("Informe os dados do comando.")
    if len(raw) > RAW_PAYLOAD_MAX_KEYS:
        raise ValueError("Os dados do comando têm campos demais.")

    payload: dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key)
        if RAW_PAYLOAD_KEY_PATTERN.match(name) is None:
            raise ValueError(f"Nome de campo não aceito: '{name[:40]}'.")
        if isinstance(value, dict):
            if len(value) > RAW_PAYLOAD_MAX_NESTED_KEYS:
                raise ValueError(f"O campo '{name}' tem subcampos demais.")
            nested: dict[str, Any] = {}
            for nested_key, nested_value in value.items():
                nested_name = str(nested_key)
                if RAW_PAYLOAD_KEY_PATTERN.match(nested_name) is None:
                    raise ValueError(f"Nome de subcampo não aceito: '{nested_name[:40]}'.")
                if isinstance(nested_value, (dict, list, tuple)):
                    raise ValueError(f"O campo '{name}.{nested_name}' aninha demais.")
                nested[nested_name] = _raw_payload_scalar(nested_value, f"{name}.{nested_name}")
            payload[name] = nested
            continue
        if isinstance(value, (list, tuple)):
            raise ValueError(f"Lista não é aceita em '{name}'.")
        payload[name] = _raw_payload_scalar(value, name)

    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > RAW_PAYLOAD_MAX_BYTES:
        raise ValueError("Os dados do comando são grandes demais.")
    return payload


def prepare_car_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    """Monta o envelope do prepare_car (360) a partir de parâmetros nomeados.

    A biblioteca serializa este dicionário sem validar nada — o `cmd_content` é
    "the full JSON payload string". Repassar JSON vindo do site seria entregar à
    nuvem um pacote que ninguém conferiu, então aqui só entram dimensões
    conhecidas, e só as que o proprietário pediu explicitamente.

    O vocabulário de `air_condition` segue os mesmos campos do payload de clima
    já usados em produção no `ac_switch` (circle/mode/operate/position/temperature/
    windlevel/wshld), confirmado pelos enums da biblioteca. As outras duas
    dimensões vêm documentadas no agendamento equivalente (361).

    `seat_setting` fica de fora de propósito: a documentação diz apenas
    "per seat 3=heat, 13=vent, 0=off", sem nomear os campos de cada assento.
    Aquecimento e ventilação de assento já têm comando próprio e verificado
    (`seat_heat`/`seat_ventilation`).
    """
    payload: dict[str, Any] = {}

    if bool_or_none(parameters.get("climate")) is True:
        requested_mode = str(parameters.get("climate_mode") or "wind").strip().lower()
        operate = "auto" if requested_mode in {"auto", "generic", "nohotcold"} else "manual"
        mode = "wind" if operate == "auto" else requested_mode
        if mode not in {"cold", "hot", "wind"}:
            raise ValueError("Modo de climatização inválido.")
        try:
            temperature = int(parameters.get("temperature", 24))
        except (TypeError, ValueError):
            raise ValueError("Temperatura inválida.") from None
        if temperature < 16 or temperature > 32:
            raise ValueError("Temperatura fora da faixa permitida.")
        try:
            wind_level = int(parameters.get("wind_level", 3))
        except (TypeError, ValueError):
            raise ValueError("Nível de ventilação inválido.") from None
        if wind_level < 1 or wind_level > 7:
            raise ValueError("Nível de ventilação fora da faixa permitida.")
        payload["air_condition"] = {
            "enable": True,
            "circle": "in",
            "mode": mode,
            "operate": operate,
            "position": "all",
            "temperature": str(temperature),
            "windlevel": str(wind_level),
            "wshld": "1" if bool_or_none(parameters.get("defrost")) is True else "0",
        }

    if bool_or_none(parameters.get("steering_wheel_heat")) is True:
        try:
            level = int(parameters.get("steering_wheel_level", 1))
        except (TypeError, ValueError):
            raise ValueError("Nível do volante inválido.") from None
        if level < 0 or level > 3:
            raise ValueError("Nível do volante fora da faixa permitida.")
        payload["steeringWheelHeatCtrl"] = {"enable": True, "level": level}

    if bool_or_none(parameters.get("mirror_heat")) is True:
        payload["rearMirrorHeating"] = {"enable": True, "value": 1}

    if payload == {}:
        raise ValueError("Escolha ao menos um item para preparar o carro.")
    return payload


def read_command_state(
    client: Any,
    resolved_vehicle_id: str,
    command: str,
    parameters: dict[str, Any],
    vehicles: list[Any] | None = None,
) -> dict[str, Any]:
    """Read one state sample and keep freshness separate from command acceptance."""
    if command not in CLIMATE_VERIFY_COMMANDS:
        return {
            "matched": False,
            "evaluable": False,
            "state": "unsupported",
            "captured_epoch": 0.0,
            "vehicles": list(vehicles or []),
        }
    selected, available = _select_command_vehicle(client, resolved_vehicle_id, vehicles)
    if selected is None:
        return {
            "matched": False,
            "evaluable": False,
            "state": "vehicle_not_found",
            "captured_epoch": 0.0,
            "vehicles": available,
        }
    status = client.get_vehicle_status(selected)
    captured_epoch = _status_capture_epoch(status)
    climate = attribute(status, "climate")
    mode = climate_mode_from_status(climate)
    profile = climate_profile_from_status(climate)
    expected_mode = expected_climate_mode(command)
    if mode == "unknown" or expected_mode is None:
        return {
            "matched": False,
            "evaluable": False,
            "state": "climate_unknown",
            "climate_mode": mode,
            "climate_profile": profile,
            "captured_epoch": captured_epoch,
            "vehicles": available,
        }
    return {
        "matched": mode == expected_mode,
        "evaluable": True,
        "state": "climate_" + mode,
        "climate_mode": mode,
        "climate_profile": profile,
        "captured_epoch": captured_epoch,
        "vehicles": available,
    }


def verify_command_state(
    client: Any,
    resolved_vehicle_id: str,
    command: str,
    parameters: dict[str, Any],
    vehicles: list[Any] | None = None,
) -> tuple[bool, bool, str]:
    sample = read_command_state(client, resolved_vehicle_id, command, parameters, vehicles)
    return bool(sample.get("matched")), bool(sample.get("evaluable")), str(sample.get("state") or "unknown")


def wait_for_command_state(
    client: Any,
    resolved_vehicle_id: str,
    command: str,
    parameters: dict[str, Any],
    command_started_at: float,
    timeout_seconds: int,
    report: Callable[[str, str, dict[str, Any] | None], None],
    stage: str,
    vehicles: list[Any] | None = None,
) -> dict[str, Any]:
    """Wait for a fresh sample without issuing another remote command."""
    timeout_seconds = max(4, min(40, int(timeout_seconds or 20)))
    deadline = time.monotonic() + timeout_seconds
    samples = 0
    last: dict[str, Any] = {
        "matched": False,
        "evaluable": False,
        "fresh": False,
        "state": "not_checked",
        "captured_epoch": 0.0,
        "samples": 0,
        "last_error": "",
    }
    current_vehicles = vehicles
    while True:
        samples += 1
        try:
            sample = read_command_state(
                client,
                resolved_vehicle_id,
                command,
                parameters,
                current_vehicles,
            )
            if isinstance(sample.get("vehicles"), list):
                current_vehicles = sample.get("vehicles")
            captured_epoch = float(sample.get("captured_epoch") or 0)
            fresh = captured_epoch <= 0 or captured_epoch >= command_started_at - 5
            sample["fresh"] = fresh
            sample["samples"] = samples
            sample["last_error"] = ""
            last = sample
            report(
                stage,
                "Veículo respondeu. Verificando se o estado novo já foi aplicado."
                if fresh else
                "O veículo respondeu com uma leitura antiga. Aguardando uma atualização nova.",
                {
                    "verification_sample": samples,
                    "state_fresh": fresh,
                    "state_evaluable": bool(sample.get("evaluable")),
                },
            )
            if bool(sample.get("matched")):
                return sample
            # A fresh evaluable sample is enough to prove that the vehicle is
            # awake and available for the second idempotent climate delivery.
            if fresh and bool(sample.get("evaluable")):
                return sample
        except Exception as exc:  # noqa: BLE001
            cooldown = login_cooldown_seconds(exc)
            if cooldown > 0:
                raise ConnectorLoginCooldownError(
                    "A Leapmotor limitou temporariamente novas autenticações. O comando continuará na fila e será retomado automaticamente.",
                    cooldown,
                ) from exc
            if is_authentication_error(exc):
                raise ConnectorAuthenticationError(clean_message(str(exc))) from exc
            last = {
                "matched": False,
                "evaluable": False,
                "fresh": False,
                "state": "verification_unavailable",
                "captured_epoch": 0.0,
                "samples": samples,
                "last_error": clean_message(str(exc)),
            }
            report(
                stage,
                "A leitura do veículo oscilou. A ação não será repetida até a etapa segura.",
                {"verification_sample": samples, "state_fresh": False, "state_evaluable": False},
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return last
        time.sleep(min(4.0, max(0.5, remaining)))


def verify_climate_state_once_after_settle(
    client: Any,
    resolved_vehicle_id: str,
    command: str,
    parameters: dict[str, Any],
    command_started_at: float,
    report: Callable[[str, str, dict[str, Any] | None], None],
    stage: str,
    vehicles: list[Any] | None = None,
    settle_seconds: float = 1.0,
) -> dict[str, Any]:
    """Faça uma única leitura curta depois do ACK, sem criar novo laço de polling.

    1.12.81 — climate_off precisa continuar podendo usar a segunda transmissão
    idempotente quando a primeira não aparece no veículo, mas não deve pagar o
    polling síncrono do remoteCtlId da biblioteca. Damos uma janela curta para
    o C10 aplicar o OFF, fazemos UMA leitura e devolvemos imediatamente. Se essa
    leitura ainda contradiz o OFF, a camada de comando pode repetir exatamente
    o mesmo estado uma única vez. A confirmação final continua na telemetria.
    """
    delay = max(0.0, min(2.0, float(settle_seconds or 0.0)))
    if delay > 0:
        time.sleep(delay)
    try:
        sample = read_command_state(
            client,
            resolved_vehicle_id,
            command,
            parameters,
            vehicles,
        )
        captured_epoch = float(sample.get("captured_epoch") or 0)
        fresh = captured_epoch <= 0 or captured_epoch >= command_started_at - 5
        sample["fresh"] = fresh
        sample["samples"] = 1
        sample["last_error"] = ""
        report(
            stage,
            "Veículo respondeu à verificação curta pós-ACK.",
            {
                "verification_sample": 1,
                "state_fresh": fresh,
                "state_evaluable": bool(sample.get("evaluable")),
                "single_probe": True,
            },
        )
        return sample
    except Exception as exc:  # noqa: BLE001
        cooldown = login_cooldown_seconds(exc)
        if cooldown > 0:
            raise ConnectorLoginCooldownError(
                "A Leapmotor limitou temporariamente novas autenticações. O comando continuará na fila e será retomado automaticamente.",
                cooldown,
            ) from exc
        if is_authentication_error(exc):
            raise ConnectorAuthenticationError(clean_message(str(exc))) from exc
        report(
            stage,
            "A verificação curta oscilou; a telemetria continuará a confirmação sem aumentar o polling.",
            {"verification_sample": 1, "state_fresh": False, "state_evaluable": False, "single_probe": True},
        )
        return {
            "matched": False,
            "evaluable": False,
            "fresh": False,
            "state": "verification_unavailable",
            "captured_epoch": 0.0,
            "samples": 1,
            "last_error": clean_message(str(exc)),
        }


def handle_command(
    payload: dict[str, Any],
    progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
    borrowed_client: Any | None = None,
    borrowed_vehicles: list[Any] | None = None,
) -> dict[str, Any]:
    """Execute one remote action with a wake-aware climate sequence.

    Locking and access commands are never repeated automatically. Climate on/off
    are state-idempotent and may receive one protected second delivery, but only
    after the connector has checked whether the first delivery merely woke the
    vehicle or already changed the HVAC state.
    """

    def report(stage: str, message: str, extra: dict[str, Any] | None = None) -> None:
        if progress is None:
            return
        # 1.12.56 — o diário de progresso é chamado várias vezes por comando e
        # nunca teve contador. Se ele custar, custa dentro de handle_command.
        report_started = time.monotonic()
        try:
            progress(stage, message, extra)
        except Exception:
            pass
        finally:
            phase_latency_ms["progress_ms"] += int(round((time.monotonic() - report_started) * 1000))

    credentials = payload.get("credentials")
    if not isinstance(credentials, dict):
        raise ValueError("Credenciais do comando ausentes.")
    vehicle_id = require_text(payload, "vehicle_id", "o identificador do veículo", 190)
    vehicle_vin = str(payload.get("vehicle_vin") or "").strip()[:40]
    command = require_text(payload, "command", "o comando remoto", 80)
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {}
    if command not in ALL_COMMAND_METHODS:
        raise ValueError("Comando remoto não suportado pelo conector.")
    if command in EXPERIMENTAL_COMMAND_METHODS:
        confirmed = str(parameters.get("experimental_confirmed") or "").strip().lower()
        if confirmed not in {"1", "true", "on", "yes"}:
            raise ValueError("O comando experimental exige confirmação explícita do proprietário.")
    if command in VEHICLE_MOTION_COMMANDS:
        # Segundo trava, próprio dos comandos que movem o carro. A liberação do
        # administrador e a confirmação experimental dizem que o recurso está
        # aberto para este proprietário; esta diz que, agora, ele está junto do
        # carro e com ele à vista. Nenhum aplicativo consegue verificar isso — o
        # que dá para fazer é exigir que seja declarado, para que um toque
        # distraído não ponha o carro em movimento.
        acknowledged = str(parameters.get("motion_acknowledged") or "").strip().lower()
        if acknowledged not in {"1", "true", "on", "yes"}:
            raise ValueError(
                "Este comando movimenta o veículo. Confirme que você está junto dele e com ele à vista."
            )
    operation_password = require_text(credentials, "operation_password", "o PIN do veículo", 20)
    wake_on_sleep = bool(payload.get("wake_before", True))
    verify_after = bool(payload.get("verify_after", True))
    stale_snapshot = bool(payload.get("stale_snapshot", False))
    try:
        wake_timeout = max(12, min(45, int(payload.get("wake_timeout_seconds") or 30)))
    except (TypeError, ValueError):
        wake_timeout = 30

    temp_dir = secure_temp_directory()
    client = borrowed_client
    client_is_borrowed = borrowed_client is not None
    borrowed_original_operation_password = getattr(borrowed_client, "operation_password", None) if borrowed_client is not None else None
    if borrowed_client is not None:
        try:
            borrowed_client.operation_password = operation_password
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("A sessão ativa não permite preparar o PIN do veículo.") from exc

    result: Any = None
    identifier_source = ""
    resolved_vehicle_id = ""
    resolved_list: list[Any] | None = borrowed_vehicles
    method: Any = None
    wake_info: dict[str, Any] = {"attempted": False, "method": None}
    confirmation_pending = False
    confirmation_reason: str | None = None
    command_attempts = 0
    session_attempts = 0
    verified_by_gateway = False
    safe_retry_performed = False
    verification_state = "not_checked"
    verification_samples = 0
    execution_warning: str | None = None
    safe_retry_strategy: str | None = None
    active_climate_profile = "generic"
    window_native_scale = 100
    climate_dispatch_strategy: str | None = None
    command_dispatched = False
    cloud_accepted = False
    dispatch_ack = "not_dispatched"
    remote_result_status = "not_started"
    remote_result_summary: dict[str, Any] = {"type": "NoneType", "returned": False, "payload": "none"}
    remote_result_signal_value = "unknown"
    remote_result_evidence = "not_dispatched"
    result_poll_deferred = False
    command_started_at = time.time()
    phase_latency_ms: dict[str, int] = {
        "session_prepare_ms": 0,
        "dispatch_ms": 0,
        "verification_ms": 0,
        "progress_ms": 0,
    }

    def timed_remote_call(callable_value: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        try:
            return callable_value(*args, **kwargs)
        finally:
            phase_latency_ms["dispatch_ms"] += int(round((time.monotonic() - started) * 1000))

    def timed_wait_for_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
        started = time.monotonic()
        try:
            return wait_for_command_state(*args, **kwargs)
        finally:
            phase_latency_ms["verification_ms"] += int(round((time.monotonic() - started) * 1000))


    def timed_single_verification(*args: Any, **kwargs: Any) -> dict[str, Any]:
        started = time.monotonic()
        try:
            return verify_climate_state_once_after_settle(*args, **kwargs)
        finally:
            phase_latency_ms["verification_ms"] += int(round((time.monotonic() - started) * 1000))

    def close_client(force: bool = False) -> None:
        nonlocal client, client_is_borrowed
        if client is None:
            return
        if client_is_borrowed and not force:
            return
        try:
            client.close()
        except Exception:
            pass
        client = None
        client_is_borrowed = False

    def open_client(attempt: int) -> tuple[Any, str, list[Any] | None, Any, str]:
        nonlocal client, session_attempts, client_is_borrowed
        session_attempts += 1
        if attempt == 1 and borrowed_client is not None:
            client = borrowed_client
            client_is_borrowed = True
            resolved_id, vehicles, source = resolve_command_vehicle(
                client, vehicle_id, vehicle_vin, borrowed_vehicles
            )
        else:
            attempt_dir = temp_dir / f"command-{attempt}"
            attempt_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            client = create_client(credentials, attempt_dir, operation_password, request_timeout_seconds=32)
            client_is_borrowed = False
            client.login()
            resolved_id, vehicles, source = resolve_command_vehicle(client, vehicle_id, vehicle_vin)
        method_name = ALL_COMMAND_METHODS[command]
        selected_method = getattr(client, method_name, None)
        if not callable(selected_method):
            raise RuntimeError("A versão instalada da biblioteca não possui este comando.")
        if vehicles is not None and callable(getattr(client, "get_vehicle_list", None)):
            client.get_vehicle_list = lambda: vehicles
        return client, resolved_id, vehicles, selected_method, source

    def classify_accepted_ambiguity(exc: Exception) -> bool:
        nonlocal result, confirmation_pending, confirmation_reason, command_dispatched, cloud_accepted, dispatch_ack, remote_result_status, remote_result_summary, remote_result_signal_value, remote_result_evidence
        if not (is_remote_command_confirmation_timeout(exc) or is_remote_command_result_session_error(exc)):
            return False
        confirmation_pending = True
        confirmation_reason = (
            "result_session_refresh"
            if is_remote_command_result_session_error(exc)
            else "result_timeout"
        )
        result = {
            "accepted": True,
            "confirmation_pending": True,
            "confirmation_reason": confirmation_reason,
        }
        command_dispatched = True
        cloud_accepted = True
        dispatch_ack = "cloud_accepted_result_pending"
        remote_result_status = confirmation_reason
        remote_result_summary = safe_remote_result_summary(result)
        remote_result_signal_value = "unknown"
        remote_result_evidence = "cloud_acknowledged_but_result_query_inconclusive"
        return True

    def raise_classified(exc: Exception) -> None:
        cooldown = login_cooldown_seconds(exc)
        if cooldown > 0:
            raise ConnectorLoginCooldownError(
                "A Leapmotor limitou temporariamente novas autenticações. O comando continuará na fila e será retomado automaticamente.",
                cooldown,
            ) from exc
        if is_authentication_error(exc):
            raise ConnectorAuthenticationError(clean_message(str(exc))) from exc
        if is_transient_cloud_error(exc):
            raise ConnectorTemporaryError(reconnect_message(exc)) from exc
        raise RuntimeError(clean_message(str(exc))) from exc

    def dispatch_once(stage: str, message: str, attempt: int) -> Exception | None:
        nonlocal result, command_attempts, command_dispatched, cloud_accepted, dispatch_ack, remote_result_status, remote_result_summary, remote_result_signal_value, remote_result_evidence, result_poll_deferred, confirmation_pending, confirmation_reason
        report(stage, message, {
            "attempt": attempt,
            "climate_profile": active_climate_profile if command == "climate_off" else None,
            "dispatch_strategy": climate_dispatch_strategy if command == "climate_off" else None,
        })
        command_attempts = max(command_attempts, attempt)
        try:
            dispatched = timed_remote_call(
                execute_vehicle_command_ack_first,
                method,
                command,
                resolved_vehicle_id,
                parameters,
                active_climate_profile,
                window_native_scale,
            )
            result, deferred_now = dispatched
            result_poll_deferred = bool(deferred_now)
            command_dispatched = True
            cloud_accepted = True
            remote_result_summary = safe_remote_result_summary(result)
            remote_result_signal_value = remote_result_signal(remote_result_summary)
            if result_poll_deferred:
                confirmation_pending = True
                confirmation_reason = "result_poll_deferred"
                dispatch_ack = "cloud_accepted_result_pending"
                remote_result_status = "ack_only"
                remote_result_evidence = "remote_write_returned_result_poll_deferred_to_telemetry"
            else:
                dispatch_ack = "library_returned"
                remote_result_status = "completed"
                remote_result_evidence = "library_method_completed_without_exception"
            return None
        except Exception as exc:  # noqa: BLE001
            if classify_accepted_ambiguity(exc):
                report(
                    "verifying",
                    "A nuvem recebeu a ação, mas ainda não devolveu a confirmação final do veículo.",
                    {"attempt": attempt, "cloud_accepted": True},
                )
                return None
            return exc

    try:
        report(
            "preparing",
            "Reutilizando a sessão autenticada da conta para o comando." if borrowed_client is not None
            else "Preparando uma sessão exclusiva para o comando.",
            {"session_reused": borrowed_client is not None},
        )
        session_prepare_started = time.monotonic()
        try:
            _, resolved_vehicle_id, resolved_list, method, identifier_source = open_client(1)
        except Exception as exc:  # noqa: BLE001
            raise_classified(exc)
        finally:
            phase_latency_ms["session_prepare_ms"] += int(round((time.monotonic() - session_prepare_started) * 1000))

        if command in {"windows_open", "windows_close", "windows_position"}:
            selected_window_vehicle, resolved_list = _select_command_vehicle(
                client,
                resolved_vehicle_id,
                resolved_list,
            )
            window_native_scale = window_command_native_scale(selected_window_vehicle)
            report(
                "preparing",
                "Preparando comando de janelas na escala nativa confirmada para este modelo.",
                {
                    "window_native_scale": window_native_scale,
                    "single_delivery": True,
                },
            )

        is_climate_state_command = command in CLIMATE_VERIFY_COMMANDS
        can_safe_retry = command in SAFE_STATE_RETRY_COMMANDS
        if command == "climate_off":
            climate_dispatch_strategy = "c10_ac_switch_off"
            report(
                "preparing",
                "Preparando o desligamento completo da climatização pelo ac_switch do C10.",
                {"single_delivery": True},
            )
        elif command == "climate_on":
            climate_dispatch_strategy = "c10_auto_nohotcold"
            report(
                "preparing",
                "Preparando a climatização em AUTO com o setpoint mais recente.",
                {"single_delivery": True},
            )
        first_error = dispatch_once(
            "executing",
            "Enviando o estado solicitado da climatização."
            if command == "climate_off" else
            "Enviando a ação diretamente ao veículo.",
            1,
        )

        if first_error is not None and wake_on_sleep and is_vehicle_sleep_error(first_error):
            report("vehicle_waking", "Veículo em repouso. Solicitando despertar antes da ação.")
            wake_info = try_wake_vehicle(client, resolved_vehicle_id)
            if not wake_info.get("attempted"):
                raise ConnectorTemporaryError(
                    "O veículo está em repouso e a biblioteca instalada não oferece uma operação de despertar separada."
                ) from first_error
            if wake_info.get("failed") and not wake_info.get("temporary"):
                raise ConnectorTemporaryError(
                    str(wake_info.get("message") or "Não foi possível acordar o veículo agora.")
                ) from first_error
            wait_sample = timed_wait_for_state(
                client,
                resolved_vehicle_id,
                command,
                parameters,
                command_started_at,
                min(wake_timeout, 24),
                report,
                "vehicle_waking",
                resolved_list,
            ) if is_climate_state_command else {"matched": False, "fresh": True, "evaluable": False, "samples": 0}
            verification_samples += int(wait_sample.get("samples") or 0)
            report("vehicle_awake", "Veículo disponível. Preparando a ação solicitada.")
            first_error = dispatch_once(
                "climate_dispatching" if is_climate_state_command else "executing",
                "Veículo disponível. Enviando a climatização agora."
                if is_climate_state_command else
                "Veículo disponível. Enviando a ação agora.",
                2,
            )
            if is_climate_state_command:
                safe_retry_performed = True

        if first_error is not None:
            if can_safe_retry and is_transient_cloud_error(first_error):
                # A timeout may have happened before or immediately after the
                # write. Climate state is idempotent, so verify first and use the
                # single protected second delivery only when still necessary.
                report(
                    "retry_wait",
                    "A nuvem demorou a responder. Verificando o veículo antes de repetir a climatização.",
                    {"retry_after_seconds": 8},
                )
            else:
                raise_classified(first_error)

        if is_climate_state_command and verify_after:
            stage = "vehicle_waking" if stale_snapshot or confirmation_reason == "result_timeout" else "climate_verifying"
            if command == "climate_off" and result_poll_deferred:
                # 1.12.81 — o OFF C10 não espera o polling interno da biblioteca.
                # Uma única leitura curta mantém a decisão segura sobre a segunda
                # transmissão idempotente sem criar um novo laço de polling.
                initial_sample = timed_single_verification(
                    client,
                    resolved_vehicle_id,
                    command,
                    parameters,
                    command_started_at,
                    report,
                    stage,
                    resolved_list,
                    1.0,
                )
            else:
                initial_sample = timed_wait_for_state(
                    client,
                    resolved_vehicle_id,
                    command,
                    parameters,
                    command_started_at,
                    min(wake_timeout, 30),
                    report,
                    stage,
                    resolved_list,
                )
            verification_samples += int(initial_sample.get("samples") or 0)
            verification_state = str(initial_sample.get("state") or "unknown")
            if bool(initial_sample.get("matched")):
                verified_by_gateway = True
                confirmation_pending = False
                confirmation_reason = None
                report("verifying", "Climatização confirmada por uma leitura nova do veículo.", {"verified_by_gateway": True})
            elif can_safe_retry and command_attempts < 2:
                report(
                    "vehicle_awake",
                    "O veículo já está disponível, mas a climatização ainda não mudou.",
                    {
                        "state_fresh": bool(initial_sample.get("fresh")),
                        "state_evaluable": bool(initial_sample.get("evaluable")),
                    },
                )
                safe_retry_strategy = "repeat_exact_state_command"
                report(
                    "climate_dispatching",
                    "Repetindo uma segunda e última vez o mesmo estado de climatização.",
                    {
                        "safe_retry": True,
                        "attempt": 2,
                        "retry_strategy": safe_retry_strategy,
                    },
                )
                command_attempts = 2
                safe_retry_performed = True
                retry_error: Exception | None = None
                try:
                    retry_dispatched = timed_remote_call(
                        execute_vehicle_command_ack_first,
                        method,
                        command,
                        resolved_vehicle_id,
                        parameters,
                        active_climate_profile,
                        window_native_scale,
                    )
                    result, retry_deferred = retry_dispatched
                    result_poll_deferred = bool(result_poll_deferred or retry_deferred)
                    command_dispatched = True
                    cloud_accepted = True
                    if retry_deferred:
                        dispatch_ack = "cloud_accepted_result_pending"
                        remote_result_status = "ack_only"
                        remote_result_evidence = "remote_write_returned_result_poll_deferred_to_telemetry"
                except Exception as exc:  # noqa: BLE001
                    if not classify_accepted_ambiguity(exc):
                        retry_error = exc

                if command == "climate_off" and result_poll_deferred:
                    # A segunda e última transmissão OFF já saiu por ACK-first.
                    # Não abra outro ciclo síncrono de leitura aqui: a telemetria
                    # FAST já existente decide o estado físico final.
                    verification_state = "after_safe_retry:telemetry_pending"
                    if retry_error is not None:
                        raise_classified(retry_error)
                    confirmation_pending = True
                    confirmation_reason = "telemetry_pending_after_safe_retry"
                    report(
                        "verifying",
                        "Segundo OFF enviado; confirmação física segue pela telemetria sem novo polling síncrono.",
                        {"safe_retry": True, "telemetry_confirmation": True},
                    )
                else:
                    final_sample = timed_wait_for_state(
                        client,
                        resolved_vehicle_id,
                        command,
                        parameters,
                        time.time() - 1,
                        18,
                        report,
                        "climate_verifying",
                        resolved_list,
                    )
                    verification_samples += int(final_sample.get("samples") or 0)
                    verification_state = f"after_wake_retry:{str(final_sample.get('state') or 'unknown')}"
                    if bool(final_sample.get("matched")):
                        verified_by_gateway = True
                        confirmation_pending = False
                        confirmation_reason = None
                        report("verifying", "Climatização confirmada depois da etapa pós-despertar.", {"verified_by_gateway": True})
                    elif bool(final_sample.get("evaluable")) and bool(final_sample.get("fresh")):
                        confirmation_pending = True
                        confirmation_reason = "state_not_applied_after_wake_retry"
                        execution_warning = "climate_not_applied_after_safe_retry"
                    elif retry_error is not None:
                        raise_classified(retry_error)
                    else:
                        confirmation_pending = True
                        confirmation_reason = confirmation_reason or "telemetry_pending"
            else:
                confirmation_pending = True
                if bool(initial_sample.get("evaluable")) and bool(initial_sample.get("fresh")):
                    confirmation_reason = "state_not_applied_after_wake_retry"
                    execution_warning = "climate_not_applied_after_safe_retry"
                else:
                    confirmation_reason = confirmation_reason or "verification_unavailable"
        elif first_error is not None:
            raise_classified(first_error)

        if not is_climate_state_command and first_error is None and not command_dispatched:
            # Defensive invariant for non-idempotent actions.
            raise ConnectorTemporaryError("A ação não chegou à etapa de envio e foi encerrada sem repetição automática.")

        not_applied = bool(
            execution_warning == "climate_not_applied_after_safe_retry"
            and confirmation_reason == "state_not_applied_after_wake_retry"
        )
        if not_applied:
            # A fresh, evaluable sample contradicted the requested state. This is
            # terminal for this request: do not pretend success and do not issue a
            # third delivery. A later user action receives a new request id.
            confirmation_pending = False
        elif verified_by_gateway:
            confirmation_pending = False
        elif command_dispatched or cloud_accepted:
            # Uma ação aceita, mas ainda não verificada, deve manter o mesmo
            # estado em todo o resultado e no diário do Gateway.
            confirmation_pending = True
        if verified_by_gateway:
            message = "A ação foi executada e confirmada por uma leitura nova do veículo."
        elif not_applied:
            message = (
                "A nuvem recebeu o comando, mas uma leitura nova confirmou que a climatização continuou ligada."
                if command == "climate_off" else
                "A nuvem recebeu o comando, mas uma leitura nova confirmou que o modo de climatização solicitado não foi aplicado."
            )
        elif safe_retry_performed:
            message = "O veículo acordou e a climatização foi enviada na etapa pós-despertar. A telemetria continuará confirmando o estado."
        elif confirmation_pending and command in SENTRY_COMMANDS:
            if confirmation_reason == "result_timeout":
                message = "O Sentinela foi aceito pela nuvem, mas a consulta do resultado remoto expirou. A telemetria verificará se o estado sentry_mode é exposto, sem reenviar o comando."
            elif confirmation_reason == "result_session_refresh":
                message = "O Sentinela foi aceito pela nuvem, mas a sessão expirou durante a consulta do resultado. A telemetria verificará o estado sem reenviar o comando."
            else:
                message = "A biblioteca concluiu o comando Sentinela sem exceção. A telemetria verificará o estado sem repetir o comando experimental."
        elif confirmation_pending:
            message = "A ação foi aceita pela nuvem. O estado será confirmado pela telemetria sem repetir comandos não idempotentes."
        elif command in SENTRY_COMMANDS:
            message = "O fluxo remoto do Sentinela terminou sem exceção. Isso confirma o processamento da chamada, mas não prova o estado físico enquanto sentry_mode não for publicado."
        else:
            message = "A ação foi enviada ao veículo. Atualizando o estado automaticamente."

        # This is progress only; command_journal_finish is the sole point that
        # turns the request into sent/completed after this function returns.
        report(
            "verifying" if confirmation_pending and not verified_by_gateway else "executing",
            message,
            {
                "confirmation_pending": confirmation_pending,
                "verified_by_gateway": verified_by_gateway,
                "cloud_accepted": cloud_accepted,
            },
        )
        return {
            "ok": True,
            "message": message,
            "command": command,
            "experimental": command in EXPERIMENTAL_COMMAND_METHODS,
            "result_type": type(result).__name__,
            "connector_version": CONNECTOR_VERSION,
            "library_version": package_version(),
            "wake_attempted": bool(wake_info.get("attempted")),
            "wake_method": wake_info.get("method"),
            "wake_strategy": (
                "staged_climate_after_wake" if bool(wake_info.get("attempted")) and is_climate_state_command else
                "fallback_after_explicit_sleep" if bool(wake_info.get("attempted")) else
                "command_direct"
            ),
            "stale_snapshot_received": stale_snapshot,
            "intended_climate_on": (command != "climate_off") if is_climate_state_command else None,
            "attempts": command_attempts,
            "session_attempts": session_attempts,
            "verification_requested": bool(verify_after),
            "confirmation_pending": confirmation_pending,
            "confirmation_reason": confirmation_reason,
            "identifier_source": identifier_source or ("vin_hint" if vehicle_vin else "resolved"),
            "command_dispatched": command_dispatched,
            "cloud_accepted": cloud_accepted,
            "dispatch_ack": dispatch_ack,
            "remote_result_status": remote_result_status,
            "remote_result_evidence": remote_result_evidence,
            "remote_result_signal": remote_result_signal_value,
            "remote_result_summary": remote_result_summary if command in SENTRY_COMMANDS else {},
            "result_poll_deferred": result_poll_deferred,
            "sentry_probe": command in SENTRY_COMMANDS,
            "session_reused": borrowed_client is not None,
            "verified_by_gateway": verified_by_gateway,
            "vehicle_confirmed": verified_by_gateway,
            "not_applied": not_applied,
            "applied": True if verified_by_gateway else (False if not_applied else None),
            "final_outcome": "confirmed" if verified_by_gateway else ("not_applied" if not_applied else "confirmation_pending"),
            "safe_retry_performed": safe_retry_performed,
            "safe_retry_strategy": safe_retry_strategy,
            "climate_dispatch_strategy": climate_dispatch_strategy,
            "climate_profile_used": None,
            "window_native_scale_used": (
                window_native_scale
                if command in {"windows_open", "windows_close", "windows_position"}
                else None
            ),
            "verification_state": verification_state,
            "verification_samples": verification_samples,
            "execution_warning": execution_warning,
            "phase_latency_ms": dict(phase_latency_ms),
        }
    finally:
        if borrowed_client is not None:
            try:
                borrowed_client.operation_password = borrowed_original_operation_password
            except Exception:
                pass
        close_client()
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
    if action == "driving_record":
        emit(handle_driving_record(payload))
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
