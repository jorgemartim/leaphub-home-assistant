from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
CONNECTOR = (APP / "connector.py").read_text(encoding="utf-8")
SERVER = (APP / "connector_server.py").read_text(encoding="utf-8")
TELEMETRY = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
CONFIG = (APP / "config.yaml").read_text(encoding="utf-8")
TARGET = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_release_version_and_staged_publication():
    # 1.12.116: release metadata follows RELEASE_TARGET instead of pinning
    # this feature regression test forever to 1.12.115. All proximity and
    # physical-safety assertions below remain unchanged.
    assert f'CONNECTOR_VERSION = "{TARGET}"' in CONNECTOR
    assert f'VERSION = "{TARGET}"' in SERVER
    assert f'ENGINE_VERSION = "{TARGET}"' in TELEMETRY

    match = re.search(
        r'^version:\s*"([^"]+)"\s*$',
        CONFIG,
        flags=re.MULTILINE,
    )
    assert match is not None
    assert _version_tuple(match.group(1)) <= _version_tuple(TARGET)


def test_realtime_scope_is_only_mobile_presence_commands():
    assert 'REALTIME_PROXIMITY_COMMANDS = frozenset({"lock", "unlock", "trunk_open"})' in CONNECTOR
    assert 'origin != "mobile_proximity"' in CONNECTOR
    assert 'REALTIME_PROXIMITY_MAX_FUTURE_SECONDS = 20.0' in CONNECTOR


def test_final_dispatch_fence_exists():
    marker = 'ensure_realtime_proximity_fresh(payload)\n            dispatched = timed_remote_call('
    assert marker in CONNECTOR
    assert CONNECTOR.index(marker) < CONNECTOR.index('execute_vehicle_command_ack_first,', CONNECTOR.index(marker))


def test_gateway_worker_never_queues_realtime_presence():
    assert 'account_lock.acquire(blocking=False)' in SERVER
    assert 'SEMAPHORE.acquire(blocking=False, priority=True)' in SERVER
    assert 'A conta está ocupada; a intenção de proximidade foi descartada sem envio.' in SERVER
    assert 'O Connector está ocupado; a intenção de proximidade foi descartada sem envio.' in SERVER


def test_auth_cooldown_never_reschedules_realtime_presence():
    assert 'if realtime_proximity:' in SERVER
    assert 'presença descartada sem reenvio.' in SERVER
    assert 'retry_after_seconds = 0' in SERVER


def test_idempotency_binds_deadline_and_origin():
    assert '"request_origin": str(payload.get("request_origin") or "")[:40]' in SERVER
    assert '"realtime_proximity": bool(payload.get("realtime_proximity"))' in SERVER
    assert '"realtime_expires_at_epoch": int(payload.get("realtime_expires_at_epoch") or 0)' in SERVER


def test_telemetry_has_fences_on_all_command_routes():
    assert TELEMETRY.count('connector.ensure_realtime_proximity_fresh(payload)') >= 4


def test_physical_and_cadence_contracts_remain_frozen():
    assert 'SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}' in CONNECTOR
    assert 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close"}' in CONNECTOR
    assert 'COMMAND_POST_DISPATCH_EARLY_CADENCE = (5, 5, 8)' in TELEMETRY
    assert 'TRIP_DRIVING_SECONDS_DEFAULT = 8' in TELEMETRY
    assert 'if command in {"windows_open", "windows_close"} and window_native_scale == 10:' in CONNECTOR
    assert 'params["wshld"] = "0"' in CONNECTOR
