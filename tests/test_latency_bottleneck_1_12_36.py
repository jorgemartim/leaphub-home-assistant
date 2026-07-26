from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("connection_orchestrator_latency_test", ROOT / "leaphub_gateway" / "connection_orchestrator.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ConnectionOrchestrator = MODULE.ConnectionOrchestrator

CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")


def test_bottleneck_uses_granular_p95_phases() -> None:
    coordinator = ConnectionOrchestrator()
    coordinator.record_command_latency(
        "staging",
        account_wait_ms=100,
        connector_slot_ms=20,
        session_prepare_ms=80,
        dispatch_ms=900,
        verification_ms=50,
        remote_execute_ms=1030,
        total_ms=1150,
    )
    coordinator.record_command_latency(
        "staging",
        account_wait_ms=150,
        connector_slot_ms=10,
        session_prepare_ms=70,
        dispatch_ms=1200,
        verification_ms=40,
        remote_execute_ms=1310,
        total_ms=1470,
    )
    latency = coordinator.snapshot("staging")["command_latency"]
    assert latency["dispatch_p95_ms"] == 1200
    assert latency["session_prepare_p95_ms"] == 80
    assert latency["verification_p95_ms"] == 50
    assert latency["primary_bottleneck"] == "dispatch"


def test_connector_and_worker_expose_safe_phase_latency() -> None:
    assert 'phase_latency_ms: dict[str, int]' in CONNECTOR
    assert '"phase_latency_ms": dict(phase_latency_ms)' in CONNECTOR
    assert '"session_prepare_ms": int(phase_latency.get("session_prepare_ms") or 0)' in SERVER
    assert 'preparo_sessao=%sms' in SERVER
    assert 'dispatch=%sms' in SERVER
    assert 'verificacao=%sms' in SERVER
