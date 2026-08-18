from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
T = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
C = (APP / "connector.py").read_text(encoding="utf-8")


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(name)


def test_state_is_persisted_before_visual_job_is_queued():
    body = function_source(T, "_poll_subscription")
    assert body.index("queued = self._queue_event(") < body.index("self._queue_visual_render(")


def test_cloud_collection_explicitly_disables_image_render():
    body = function_source(T, "_collect_with_session_locked")
    assert body.count("include_official_image=False") == 2
    assert "render_official_visual_snapshot" not in body


def test_visual_worker_cannot_receive_cloud_client_or_command_path():
    queue = function_source(T, "_queue_visual_render")
    worker = function_source(T, "_render_visual_background")
    helper = function_source(C, "render_official_visual_snapshot")
    combined = queue + worker + helper
    for forbidden in (
        "LeapmotorApiClient", "operation_password", "client.login(",
        "_dispatch_timeout(", "_session_operation_lock(", "handle_command(",
    ):
        assert forbidden not in combined
    assert "allow_network=False" in helper


def test_debug_gallery_is_not_generated_during_normal_telemetry():
    body = function_source(C, "official_visual_image_payload")
    assert "if force_debug_package:" in body
    assert "force=True" in body


def test_control_guardrails_remain_exact():
    assert 'SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}' in C
    assert 'return method(vehicle_id, params={"operate": "off"})' in C
    assert "command_attempts < 2" in C
    assert 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close"}' in C
    assert 'numeric_map = {0: "auto", 1: "cooling", 3: "heating"}' in T


def test_visual_worker_is_single_fifo_and_shutdown_is_orderly():
    assert 'thread_name_prefix="leaphub-visual"' in T
    assert "visual_pool.shutdown(wait=True, cancel_futures=False)" in T
