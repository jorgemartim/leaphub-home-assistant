from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


failures: list[str] = []
def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    connections: set[int] = set()
    requests = 0
    active = 0
    max_active = 0
    guard = threading.Lock()
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        type(self).connections.add(id(self.connection))
        type(self).requests += 1
        with type(self).guard:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
        if payload.get("action") == "parallel":
            time.sleep(0.25)
        raw = json.dumps({"ok": True, "accepted": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(raw)
        with type(self).guard:
            type(self).active -= 1
    def log_message(self, *_args):
        return


with tempfile.TemporaryDirectory(prefix="leaphub-1-12-16-") as tmp:
    base = Path(tmp)
    os.environ["LEAPHUB_RUNTIME_DIR"] = str(base)
    os.environ["LEAPHUB_BETA_GATEWAY_SECRET"] = "b" * 32
    os.environ["LEAPHUB_PRODUCTION_GATEWAY_SECRET"] = "p" * 32
    os.environ["LEAPHUB_BETA_INTERNAL_URL"] = "http://127.0.0.1:9/beta"
    os.environ["LEAPHUB_PRODUCTION_INTERNAL_URL"] = "http://127.0.0.1:9/prod"
    os.environ["LEAPHUB_ENVIRONMENT"] = "staging"
    privacy = load_module("leaphub_privacy", APP / "privacy.py")
    ocpp = load_module("leaphub_ocpp_1_12_16", APP / "ocpp_gateway.py")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    target = ocpp.ApiTarget("test", f"http://127.0.0.1:{httpd.server_address[1]}/internal", "s" * 32)
    try:
        first = ocpp.api_call(target, {"action": "health"}, 3.0)
        second = ocpp.api_call(target, {"action": "health"}, 3.0)
        check(first.get("ok") and second.get("ok"), "Chamadas persistentes não responderam")
        check(ApiHandler.requests == 2, "Quantidade de chamadas inesperada")
        check(len(ApiHandler.connections) == 1, "OCPP abriu uma nova conexão TCP para cada evento")
        started = time.monotonic()
        errors: list[Exception] = []
        def parallel_call() -> None:
            try:
                ocpp.api_call(target, {"action": "parallel"}, 3.0)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        workers = [threading.Thread(target=parallel_call) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(timeout=3)
        elapsed = time.monotonic() - started
        check(not errors, f"Chamadas OCPP paralelas falharam: {errors}")
        check(ApiHandler.max_active >= 2 and elapsed < 0.48, "Pool persistente serializou wallboxes diferentes")
    finally:
        ocpp._drop_api_connection(target)
        httpd.shutdown(); httpd.server_close(); thread.join(timeout=3)

    source = (APP / "ocpp_gateway.py").read_text(encoding="utf-8")
    telemetry = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    validator = (ROOT / ".github/scripts/validate_repository.py").read_text(encoding="utf-8")
    check("effective_connections = len(CONNECTIONS) -" in source, "Reconexão não desconta conexão substituída")
    check("if unavailable:" in source and "raise RuntimeError" in source, "Indisponibilidade pode virar 401")
    check("ocpp_action='Heartbeat'" in source, "Heartbeat pendente não é consolidado")
    check("if streak >= 6:" in telemetry, "Repouso ainda demora consultas demais")
    check("renovada por refresh durante a leitura de mensagens" in telemetry, "Mensagens ainda forçam relogin direto")
    check('required = ("name", "version", "slug", "description", "arch")' in validator, "Validador ainda exige imagem GHCR")
    check('version: "1.12.21"' in (APP / "config.yaml").read_text(), "Versão do App divergente")

if failures:
    raise SystemExit("full resilience 1.12.21 failed:\n- " + "\n- ".join(failures))
print({"ok": True, "checks": 12, "version": "1.12.21"})
