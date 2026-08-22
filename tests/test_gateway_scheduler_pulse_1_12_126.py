from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
SOURCE = APP / "telemetry_engine.py"
TARGET = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()


def load_engine_module():
    app_path = str(APP)
    if app_path not in sys.path:
        sys.path.insert(0, app_path)
    if "leaphub_connector" not in sys.modules:
        connector_spec = importlib.util.spec_from_file_location("leaphub_connector", APP / "connector.py")
        assert connector_spec is not None and connector_spec.loader is not None
        connector_module = importlib.util.module_from_spec(connector_spec)
        sys.modules["leaphub_connector"] = connector_module
        connector_spec.loader.exec_module(connector_module)
    spec = importlib.util.spec_from_file_location("gateway_scheduler_pulse_126", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scheduler_pulse_is_signed_and_uses_dedicated_route():
    module = load_engine_module()
    secret = "s" * 48
    captured: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            captured["path"] = self.path
            captured["headers"] = dict(self.headers)
            captured["body"] = body
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true,"accepted":true}')

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        engine = object.__new__(module.TelemetryEngine)
        engine.delivery_urls = {
            "staging": f"http://127.0.0.1:{server.server_port}/beta/leap/api/internal/telemetry/events"
        }
        engine.secrets = {"staging": secret}
        ok, status = engine._send_scheduler_pulse("staging")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert ok is True
    assert status == "accepted"
    assert captured["path"] == "/beta/leap/api/internal/scheduler/pulse"
    body = captured["body"]
    headers = captured["headers"]
    assert isinstance(body, bytes)
    assert isinstance(headers, dict)
    payload = json.loads(body)
    assert set(payload) == {"gateway_version", "sent_at"}
    assert payload["gateway_version"] == TARGET
    assert tuple(int(part) for part in TARGET.split(".")) >= (1, 12, 126)
    timestamp = str(headers["X-LeapHub-Timestamp"])
    nonce = str(headers["X-LeapHub-Nonce"])
    canonical = (
        f"POST\n/beta/leap/api/internal/scheduler/pulse\n{timestamp}\n{nonce}\n"
        f"{hashlib.sha256(body).hexdigest()}"
    ).encode()
    assert headers["X-LeapHub-Signature"] == hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    assert headers["X-LeapHub-Environment"] == "staging"


def test_scheduler_pulse_is_a_separate_worker_with_safe_fallbacks():
    source = SOURCE.read_text(encoding="utf-8")
    assert f'ENGINE_VERSION = "{TARGET}"' in source
    assert 'name="leaphub-scheduler-pulse"' in source
    assert "target=self._run_scheduler_pulse" in source
    assert "SCHEDULER_PULSE_INTERVAL_SECONDS = 55.0" in source
    assert "SCHEDULER_PULSE_TIMEOUT_SECONDS = 8.0" in source
    assert 'status not in {"unconfigured", "unsupported"}' in source
    block = source[source.index("def _run_scheduler_pulse"):source.index("def _dispatch_due_subscriptions")]
    for forbidden in ("self.lock", "self.sqlite_writer_lock", "self.operation_semaphore", "self._delivery_guard"):
        assert forbidden not in block


def test_old_site_and_missing_configuration_are_non_fatal():
    module = load_engine_module()
    engine = object.__new__(module.TelemetryEngine)
    engine.delivery_urls = {"staging": ""}
    engine.secrets = {"staging": ""}
    assert engine._send_scheduler_pulse("staging") == (False, "unconfigured")
    source = SOURCE.read_text(encoding="utf-8")
    assert "if status_code == 404:" in source
    assert 'return False, "unsupported"' in source
