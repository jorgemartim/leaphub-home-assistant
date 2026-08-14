from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
TARGET = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
CONFIG = (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8")

collection = ENGINE[
    ENGINE.index("def _collect_with_session_locked"):
    ENGINE.index("def _close_session_locked")
]
execute = ENGINE[
    ENGINE.index("    def execute_command("):
    ENGINE.index("    def _collect_with_session(", ENGINE.index("    def execute_command("))
]

checks = {
    "target_1_12_86": TARGET == "1.12.86",
    "config_staged_1_12_85": 'version: "1.12.85"' in CONFIG and 'version: "1.12.86"' not in CONFIG,
    "engine_version": 'ENGINE_VERSION = "1.12.86"' in ENGINE,
    "one_shot_adapter_preserved": 'class _TelemetryOneShotClient:' in ENGINE,
    "private_status_preserved": 'return self._one_shot("_get_vehicle_status", vehicle)' in ENGINE,
    "status_helper": "def serialize_status_one_shot(item: Any)" in collection,
    "status_uses_adapter": "client=telemetry_client" in collection,
    "explicit_refresh": "refreshed = self._try_refresh_client_session(client)" in collection,
    "single_status_retry": collection.count("serialized_item = serialize_status_one_shot(item)") == 2,
    "manual_after_refresh": "Operação manual recebeu prioridade após o refresh do status." in collection,
    "manual_before_retry": "Operação manual aguardando antes da única releitura de status." in collection,
    "confirmation_reconnect_fast": "delay = 3 if command_mode else 20" in ENGINE,
    "telemetry_network_ceiling": "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in ENGINE,
    "session_lock_ceiling": "TELEMETRY_SESSION_LOCK_WAIT_CEILING_SECONDS = 5.0" in ENGINE,
    "session_lock_manual_check": 'session_lock.acquire(timeout=0.25)' in ENGINE,
    "precheck_lock_free": "self.lock.acquire(timeout=ENGINE_LOCK_COMMAND_TIMEOUT_SECONDS)" not in execute,
    "precheck_metric_zero": "engine_lock_wait_ms = 0" in execute,
    "precheck_sqlite_read": "with self._db() as db:" in execute,
    "failure_returns_payload": "def command_journal_fail(request_hash: str | None, request_id: str, exc: BaseException) -> dict[str, Any] | None:" in SERVER and "    return response" in SERVER[SERVER.index("def command_journal_fail"):SERVER.index("def command_journal_status")],
    "failure_announced": "command_journal_fail(request_hash, request_id, exc)," in SERVER and "announce_command_result_async(" in SERVER,
    "ack_first": '"lock",' in CONNECTOR and '"unlock",' in CONNECTOR and "ACK_FIRST_COMMANDS" in CONNECTOR,
    "c10_off_exact": 'return method(vehicle_id, params={"operate": "off"})' in CONNECTOR,
    "two_attempt_ceiling": "command_attempts < 2" in CONNECTOR,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("Contrato 1.12.86 R2 falhou: " + ", ".join(failed))
print({"ok": True, "checks": len(checks), "version": "1.12.86", "revision": "R2"})
