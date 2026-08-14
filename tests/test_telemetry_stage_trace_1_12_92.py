from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
TELEMETRY = (APP / "telemetry_engine.py").read_text(encoding="utf-8")


def test_trace_is_diagnostic_and_keeps_existing_network_ceiling() -> None:
    assert "TELEMETRY_STAGE_LOG_THRESHOLD_MS = 750" in TELEMETRY
    assert "TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in TELEMETRY
    assert "def log_slow_telemetry_stage(" in TELEMETRY


def test_all_account_hold_candidates_have_named_stage_markers() -> None:
    for marker in (
        "session_operation_lock_wait",
        "session_create_client",
        "session_auth_reservation",
        "session_auth_attempt_write",
        "session_login",
        "session_auth_success_bookkeeping",
        "session_auth_success_write",
        "vehicle_list_request",
        "vehicle_list_refresh",
        "message_list_request",
        "message_list_refresh",
        "status_request",
        "status_refresh",
        "serialize_vehicle",
        "collection_total",
    ):
        assert f'"{marker}"' in TELEMETRY


def test_189_private_bounded_reads_are_preserved() -> None:
    assert "def _telemetry_vehicle_list_one_shot(" in TELEMETRY
    assert "def _telemetry_message_list_one_shot(" in TELEMETRY
    assert "def _telemetry_status_one_shot(" in TELEMETRY
    assert 'getattr(client, "_get_vehicle_list", None)' in TELEMETRY
    assert 'getattr(client, "_get_message_list", None)' in TELEMETRY
    assert 'getattr(client, "_get_vehicle_status", None)' in TELEMETRY
    assert "_TelemetryOneShotClient" not in TELEMETRY
    assert "include_secondary_network=False" in TELEMETRY
