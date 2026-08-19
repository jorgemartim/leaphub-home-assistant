from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
TELEMETRY = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8")


def test_release_version_and_staged_publication():
    assert 'CONNECTOR_VERSION = "1.12.115"' in CONNECTOR
    assert 'VERSION = "1.12.115"' in SERVER
    assert 'ENGINE_VERSION = "1.12.115"' in TELEMETRY
    # O repositorio candidato permanece em 1.12.114 ate a imagem GHCR ficar
    # publica. validate_repository.py, porem, roda os contratos historicos em
    # uma copia efemera promovida para 1.12.115. O guard de publicacao do
    # validador principal garante que o config real nunca seja adiantado.
    assert (
        'version: "1.12.114"' in CONFIG
        or 'version: "1.12.115"' in CONFIG
    )


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
