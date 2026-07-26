from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "connection_orchestrator_stability_test",
    ROOT / "leaphub_gateway" / "connection_orchestrator.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ConnectionOrchestrator = MODULE.ConnectionOrchestrator

SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
TELEMETRY = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")


def test_single_account_cannot_clear_global_degradation_early() -> None:
    coordinator = ConnectionOrchestrator()
    for account in (11, 22, 11):
        coordinator.record_cloud_failure("staging", account)
    coordinator._last_error_at["staging"] -= coordinator.RECOVERY_QUIET_SECONDS + 1
    for _ in range(5):
        coordinator.record_cloud_success("staging", 11)
    state = coordinator.snapshot("staging")
    assert state["state"] == "degraded"
    assert state["recovery"]["distinct_accounts_confirmed"] == 1


def test_two_accounts_clear_only_after_quiet_window() -> None:
    coordinator = ConnectionOrchestrator()
    for account in (11, 22, 11):
        coordinator.record_cloud_failure("staging", account)
    coordinator.record_cloud_success("staging", 11)
    coordinator.record_cloud_success("staging", 22)
    assert coordinator.snapshot("staging")["state"] == "degraded"
    coordinator._last_error_at["staging"] -= coordinator.RECOVERY_QUIET_SECONDS + 1
    coordinator.record_cloud_success("staging", 22)
    assert coordinator.snapshot("staging")["state"] == "healthy"


def test_runtime_exposes_real_queue_and_account_aware_success() -> None:
    assert 'result["queue_wait_seconds"] = int(round(slot_acquired_at - queue_started))' in SERVER
    assert '"queue_account_ms": latency["account_wait_ms"]' in SERVER
    assert '"queue_connector_ms": latency["connector_slot_ms"]' in SERVER
    assert '"remote_result_bundled_with_dispatch": True' in SERVER
    assert 'payload.get("account_id") or payload.get("vehicle_id")' in SERVER
    assert "ORCHESTRATOR.record_cloud_success(environment, account_id)" in TELEMETRY


def test_snapshot_exposes_unambiguous_latency_aliases() -> None:
    coordinator = ConnectionOrchestrator()
    coordinator.record_command_latency(
        "staging",
        account_wait_ms=180,
        connector_slot_ms=20,
        session_prepare_ms=50,
        dispatch_ms=640,
        verification_ms=90,
        remote_execute_ms=780,
        total_ms=980,
    )
    latency = coordinator.snapshot("staging")["command_latency"]
    assert latency["queue_account_p95_ms"] == 180
    assert latency["queue_connector_p95_ms"] == 20
    assert latency["remote_dispatch_p95_ms"] == 640
    assert latency["remote_result_p95_ms"] is None
    assert latency["remote_result_bundled_with_dispatch"] is True
    assert latency["post_state_verify_p95_ms"] == 90
