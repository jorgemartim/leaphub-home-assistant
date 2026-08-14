from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
C = (APP / "connector.py").read_text(encoding="utf-8")
T = (APP / "telemetry_engine.py").read_text(encoding="utf-8")

def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(name)

def test_lazy_package_replaces_eager_upstream_loader():
    body = function_source(C, "_official_picture_package")
    assert "_LazyOfficialImagePackage.from_zip(raw)" in body
    assert "CarImagePackage.from_zip(raw)" not in body
    assert "class _LazyOfficialImagePackage:" in C
    assert "decoded_layer_count" in C

def test_normal_visual_encoding_is_lossless_but_latency_first():
    assert "IMAGE_WEBP_METHOD = 0" in C
    encode = function_source(C, "_encode_official_composite")
    assert "lossless=True" in encode
    assert "method=IMAGE_WEBP_METHOD" in encode
    assert "IMAGE_RENDER_CONTRACT_VERSION = 16" in C

def test_two_visual_workers_are_still_local_only():
    assert "self.visual_render_workers = 2" in T
    assert 'thread_name_prefix="leaphub-visual"' in T
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

def test_state_is_still_persisted_before_visual_queue():
    body = function_source(T, "_poll_subscription")
    assert body.index("queued = self._queue_event(") < body.index("self._queue_visual_render(")
    collect = function_source(T, "_collect_with_session_locked")
    assert collect.count("include_official_image=False") == 2

def test_polling_and_controls_are_deliberately_frozen():
    assert "COMMAND_FIRST_POLL_CEILING_SECONDS = 6" in T
    assert "INTERACTIVE_SECONDS_CEILING = 6" in T
    assert 'SAFE_STATE_RETRY_COMMANDS = {"climate_on", "climate_off"}' in C
    assert 'return method(vehicle_id, params={"operate": "off"})' in C
    assert "command_attempts < 2" in C
    assert 'ACK_FIRST_COMMANDS = {"lock", "unlock", "climate_on", "climate_off", "quick_cool", "quick_heat", "trunk_open", "trunk_close", "windows_open", "windows_close", "sunshade_open", "sunshade_close"}' in C

def test_visual_timing_is_log_only():
    body = function_source(C, "official_visual_image_payload")
    for name in ("package_ms", "render_ms", "base64_ms", "total_ms"):
        assert name in body
    assert '"render_timings_ms"' not in body
