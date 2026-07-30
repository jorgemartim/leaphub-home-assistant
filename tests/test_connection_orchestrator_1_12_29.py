from __future__ import annotations

from pathlib import Path

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("connection_orchestrator_test", ROOT / "leaphub_gateway" / "connection_orchestrator.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ConnectionOrchestrator = MODULE.ConnectionOrchestrator
TELEMETRY = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
DOCKER = (ROOT / "leaphub_gateway" / "Dockerfile").read_text(encoding="utf-8")


def test_multi_account_failures_require_quiet_multi_account_recovery() -> None:
    coordinator = ConnectionOrchestrator()
    coordinator.record_cloud_failure("staging", 11)
    coordinator.record_cloud_failure("staging", 22)
    coordinator.record_cloud_failure("staging", 11)
    state = coordinator.snapshot("staging")
    assert state["state"] == "degraded"
    assert state["affected_accounts_3m"] == 2
    assert state["automatic_reduction_active"] is True
    coordinator.record_cloud_success("staging", 11)
    coordinator.record_cloud_success("staging", 11)
    assert coordinator.snapshot("staging")["state"] == "degraded"
    coordinator._last_error_at["staging"] -= coordinator.RECOVERY_QUIET_SECONDS + 1
    coordinator.record_cloud_success("staging", 22)
    assert coordinator.snapshot("staging")["state"] == "healthy"


def test_command_latency_is_aggregated_without_identifiers() -> None:
    coordinator = ConnectionOrchestrator()
    coordinator.record_command_latency(
        "staging",
        account_wait_ms=100,
        connector_slot_ms=20,
        remote_execute_ms=500,
        total_ms=620,
    )
    coordinator.record_command_latency(
        "staging",
        account_wait_ms=200,
        connector_slot_ms=10,
        remote_execute_ms=900,
        total_ms=1110,
    )
    latency = coordinator.snapshot("staging")["command_latency"]
    assert latency["samples"] == 2
    assert latency["total_p50_ms"] == 620
    assert latency["total_p95_ms"] == 1110


def test_fast_slow_profiles_and_health_are_wired() -> None:
    assert 'ENGINE_VERSION = "1.12.59"' in TELEMETRY
    assert 'CONNECTOR_VERSION = "1.12.59"' in CONNECTOR
    assert 'VERSION = "1.12.59"' in SERVER
    assert '"collection_profile": "slow" if slow_cycle else "fast"' in TELEMETRY
    assert 'include_secondary_network=slow_cycle' in TELEMETRY
    assert 'ORCHESTRATOR.is_degraded(environment)' in TELEMETRY
    assert '"connection_orchestrator": ORCHESTRATOR.snapshot(environment)' in SERVER
    assert 'connection_orchestrator.py' in DOCKER
