from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
SPEC = importlib.util.spec_from_file_location(
    "connection_orchestrator_147_test",
    APP / "connection_orchestrator.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ConnectionOrchestrator = MODULE.ConnectionOrchestrator

TELEMETRY = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
SERVER = (APP / "connector_server.py").read_text(encoding="utf-8")


def test_single_failing_account_never_degrades_the_environment() -> None:
    coordinator = ConnectionOrchestrator()
    for _ in range(8):
        coordinator.record_cloud_failure("staging", 101)
    state = coordinator.snapshot("staging")
    assert state["state"] == "healthy"
    assert state["automatic_reduction_active"] is False
    assert coordinator.is_account_degraded("staging", 101) is True
    assert coordinator.is_account_degraded("staging", 202) is False
    isolation = state["cloud_isolation"]
    assert isolation["per_account_breaker"] is True
    assert isolation["single_account_can_degrade_environment"] is False
    assert isolation["degraded_accounts"] == 1


def test_distinct_accounts_can_still_confirm_shared_cloud_degradation() -> None:
    coordinator = ConnectionOrchestrator()
    coordinator.record_cloud_failure("staging", 101)
    coordinator.record_cloud_failure("staging", 202)
    coordinator.record_cloud_failure("staging", 101)
    state = coordinator.snapshot("staging")
    assert state["state"] == "degraded"
    assert state["affected_accounts_3m"] == 2
    assert state["cloud_isolation"]["global_distinct_accounts_required"] == 2


def test_account_probe_is_scoped_and_does_not_consume_other_accounts_turn() -> None:
    coordinator = ConnectionOrchestrator()
    for _ in range(coordinator.ACCOUNT_FAILURE_THRESHOLD):
        coordinator.record_cloud_failure("staging", 101)
    assert coordinator.claim_account_background_probe("staging", 101) is True
    assert coordinator.claim_account_background_probe("staging", 101) is False
    assert coordinator.claim_account_background_probe("staging", 202) is True


def test_local_success_after_quiet_window_clears_only_that_account() -> None:
    coordinator = ConnectionOrchestrator()
    for account in (101, 202):
        for _ in range(coordinator.ACCOUNT_FAILURE_THRESHOLD):
            coordinator.record_cloud_failure("staging", account)
    assert coordinator.is_account_degraded("staging", 101)
    assert coordinator.is_account_degraded("staging", 202)
    fingerprint = coordinator._account_fingerprint(101)
    coordinator._account_last_error_at["staging"][fingerprint] -= coordinator.ACCOUNT_RECOVERY_QUIET_SECONDS + 1
    coordinator.record_cloud_success("staging", 101)
    assert coordinator.is_account_degraded("staging", 101) is False
    assert coordinator.is_account_degraded("staging", 202) is True


def test_telemetry_backpressure_is_account_first_and_manual_commands_bypass_it() -> None:
    local_pos = TELEMETRY.index("ORCHESTRATOR.is_account_degraded(environment, account_id)")
    global_pos = TELEMETRY.index("ORCHESTRATOR.is_degraded(environment)", local_pos)
    assert local_pos < global_pos
    assert "claim_account_background_probe(environment, account_id)" in TELEMETRY
    assert "secondary_network_allowed(environment, account_id)" in TELEMETRY
    # O worker manual registra falha para diagnóstico, mas não consulta breaker antes do dispatch.
    worker = SERVER[SERVER.index("def run_command_job"):SERVER.index("class Handler")]
    assert "record_cloud_failure" in worker
    assert "is_account_degraded" not in worker
