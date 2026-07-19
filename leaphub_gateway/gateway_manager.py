#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VERSION = "1.11.83"
OPTIONS_PATH = Path(os.getenv("LEAPHUB_OPTIONS_PATH", "/data/options.json"))
RUNTIME = Path(os.getenv("LEAPHUB_RUNTIME_DIR", "/data/runtime"))
LOG_DIR = Path(os.getenv("LEAPHUB_LOG_DIR", "/data/logs"))
STATUS_PATH = RUNTIME / "unified-status.json"
RUNTIME.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_options() -> dict[str, Any]:
    try:
        value = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


OPTIONS = load_options()
LOG_LEVEL = str(OPTIONS.get("log_level") or "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("leaphub.gateway")
STOP = threading.Event()
UI_TOKEN = secrets.token_hex(24)


def secret_ok(value: Any, minimum: int = 32) -> bool:
    return len(str(value or "").strip()) >= minimum


def sanitize(line: str) -> str:
    text = str(line).replace("\x00", " ").rstrip()
    for key in ("tunnel_token", "gateway_secret", "staging_secret", "production_secret", "TUNNEL_TOKEN"):
        text = text.replace(key + "=", key + "=[protegido]")
    text = re.sub(r"(?i)(operatePassword|operation_password|password|token|authorization)=([^&\s]+)", r"\1=[protegido]", text)
    text = re.sub(r'(?i)("(?:operatePassword|operation_password|password|token|authorization)"\s*:\s*")[^"]+("?)', r'\1[protegido]\2', text)
    text = re.sub(r"(?i)(vin)=([^&\s]+)", r"\1=[VIN protegido]", text)
    text = re.sub(r'(?i)("vin"\s*:\s*")[^"]+("?)', r'\1[VIN protegido]\2', text)
    text = re.sub(r"\b[A-HJ-NPR-Z0-9]{17}\b", "[VIN protegido]", text, flags=re.IGNORECASE)
    if "eyJ" in text and len(text) > 120:
        start = text.find("eyJ")
        end = text.find(" ", start)
        if end < 0:
            end = len(text)
        text = text[:start] + "[token protegido]" + text[end:]
    return text[-4000:]


def scrub_existing_logs() -> None:
    """Remove segredos que versões antigas possam ter gravado em /data/logs."""
    for path in LOG_DIR.glob("*.log"):
        try:
            if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
                continue
            temp = path.with_suffix(path.suffix + ".scrub")
            with path.open("r", encoding="utf-8", errors="replace") as source, temp.open("w", encoding="utf-8") as target:
                for raw in source:
                    target.write(sanitize(raw) + "\n")
            os.replace(temp, path)
        except OSError as exc:
            LOG.warning("Não foi possível higienizar o log %s: %s", path.name, exc)


scrub_existing_logs()


@dataclass
class ManagedService:
    name: str
    label: str
    enabled: bool
    configured: bool
    command: list[str]
    env: dict[str, str]
    health_url: str | None = None
    process: subprocess.Popen[str] | None = None
    started_at: str | None = None
    last_exit_code: int | None = None
    restarts: int = 0
    next_start: float = 0.0
    requested_restart: bool = False
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=300))
    log_file: Any = None
    health_cache: dict[str, Any] = field(default_factory=lambda: {"ok": False, "message": "não verificado"})
    health_checked_at: float = 0.0

    def state(self) -> str:
        if not self.enabled:
            return "disabled"
        if not self.configured:
            return "needs_configuration"
        if self.process is not None and self.process.poll() is None:
            return "running"
        return "stopped"

    def start(self) -> None:
        if not self.enabled or not self.configured or STOP.is_set():
            return
        if self.process is not None and self.process.poll() is None:
            return
        self.next_start = 0.0
        self.log_file = (LOG_DIR / f"{self.name}.log").open("a", encoding="utf-8")
        env = os.environ.copy()
        env.update(self.env)
        LOG.info("Iniciando %s.", self.label)
        self.process = subprocess.Popen(
            self.command,
            cwd="/app" if Path("/app").exists() else str(Path(__file__).parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.started_at = utc_now()
        threading.Thread(target=self._capture, daemon=True).start()

    def _capture(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for raw in process.stdout:
            line = sanitize(raw)
            if not line:
                continue
            self.lines.append(line)
            try:
                self.log_file.write(line + "\n")
                self.log_file.flush()
            except Exception:
                pass
            print(f"[{self.name}] {line}", flush=True)

    def stop(self, restart: bool = False) -> None:
        self.requested_restart = restart
        process = self.process
        if process is None or process.poll() is not None:
            if restart:
                self.next_start = time.time() + 0.5
            return
        LOG.info("Parando %s.", self.label)
        process.terminate()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def supervise(self) -> None:
        if not self.enabled or not self.configured:
            return
        if self.process is None:
            if time.time() >= self.next_start:
                self.start()
            return
        code = self.process.poll()
        if code is None:
            return
        self.last_exit_code = int(code)
        self.process = None
        try:
            if self.log_file:
                self.log_file.close()
        except Exception:
            pass
        if STOP.is_set():
            return
        self.restarts += 1
        delay = 0.5 if self.requested_restart else min(30.0, 2.0 ** min(self.restarts, 5))
        self.requested_restart = False
        self.next_start = time.time() + delay
        LOG.warning("%s encerrou com código %s; reinício em %.1fs.", self.label, code, delay)

    def health(self, force: bool = False) -> dict[str, Any]:
        state = self.state()
        if state != "running":
            self.health_cache = {"ok": False, "message": state}
            return dict(self.health_cache)
        if not self.health_url:
            self.health_cache = {"ok": True, "message": "processo ativo"}
            return dict(self.health_cache)
        now = time.time()
        if not force and now - self.health_checked_at < 30:
            return dict(self.health_cache)
        previous = bool(self.health_cache.get("ok"))
        try:
            with urllib.request.urlopen(self.health_url, timeout=2.5) as response:
                payload = json.loads(response.read(4096).decode("utf-8"))
            self.health_cache = {"ok": bool(payload.get("ok")), "message": "endpoint respondeu"}
        except Exception as exc:
            self.health_cache = {"ok": False, "message": str(exc)[:160]}
        self.health_checked_at = now
        if previous != bool(self.health_cache.get("ok")):
            LOG.info("Saúde de %s mudou para %s.", self.label, "OK" if self.health_cache.get("ok") else "falha")
        return dict(self.health_cache)


def write_connector_options() -> Path:
    path = RUNTIME / "connector-options.json"
    payload = {
        "staging_secret": str(OPTIONS.get("staging_secret") or "").strip(),
        "production_secret": str(OPTIONS.get("production_secret") or "").strip(),
        "max_parallel_requests": int(OPTIONS.get("connector_max_parallel") or 2),
        "manual_wait_seconds": int(OPTIONS.get("connector_manual_wait_seconds") or 35),
        "telemetry_beta_enabled": bool(OPTIONS.get("telemetry_beta_enabled", True)),
        "telemetry_beta_internal_url": str(OPTIONS.get("telemetry_beta_internal_url") or ""),
        "telemetry_production_enabled": bool(OPTIONS.get("telemetry_production_enabled", False)),
        "telemetry_production_internal_url": str(OPTIONS.get("telemetry_production_internal_url") or ""),
        "telemetry_active_seconds": int(OPTIONS.get("telemetry_active_seconds") or 30),
        "telemetry_interactive_seconds": int(OPTIONS.get("telemetry_interactive_seconds") or 20),
        "telemetry_command_seconds": int(OPTIONS.get("telemetry_command_seconds") or 3),
        "telemetry_command_max_polls": int(OPTIONS.get("telemetry_command_max_polls") or 8),
        "telemetry_charging_seconds": int(OPTIONS.get("telemetry_charging_seconds") or 30),
        "telemetry_parked_seconds": int(OPTIONS.get("telemetry_parked_seconds") or 300),
        "telemetry_sleep_seconds": int(OPTIONS.get("telemetry_sleep_seconds") or 900),
        "telemetry_presence_window_seconds": int(OPTIONS.get("telemetry_presence_window_seconds") or 420),
        "telemetry_rate_limit_cooldown_seconds": int(OPTIONS.get("telemetry_rate_limit_cooldown_seconds") or 21600),
        "telemetry_batch_size": int(OPTIONS.get("telemetry_batch_size") or 25),
        "telemetry_retention_days": int(OPTIONS.get("telemetry_retention_days") or 7),
        "telemetry_queue_max_events": int(OPTIONS.get("telemetry_queue_max_events") or 10000),
        "log_level": LOG_LEVEL,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def ocpp_env(environment: str, port: int, internal_url: str, secret: str, maximum: int) -> dict[str, str]:
    runtime = RUNTIME / f"ocpp-{environment}"
    runtime.mkdir(parents=True, exist_ok=True)
    return {
        "LEAPHUB_INTERNAL_URL": internal_url,
        "LEAPHUB_GATEWAY_SECRET": secret,
        "LEAPHUB_ENVIRONMENT": environment,
        "LEAPHUB_OCPP_PORT": str(port),
        "LEAPHUB_RUNTIME_DIR": str(runtime),
        "LEAPHUB_STATUS_FILE": str(runtime / "status.json"),
        "LEAPHUB_PID_FILE": str(runtime / "gateway.pid"),
        "LEAPHUB_LOG_FILE": str(runtime / "gateway.log"),
        "LEAPHUB_SERVICE_NAME": f"leaphub-ocpp-{environment}",
        "LEAPHUB_GATEWAY_MODE": "home_assistant_tunnel",
        "LEAPHUB_GATEWAY_PROVIDER": "home_assistant_tunnel",
        "LEAPHUB_OCPP_MAX_CONNECTIONS": str(maximum),
        "LEAPHUB_OCPP_LOG_LEVEL": LOG_LEVEL,
    }


APP_DIR = Path(__file__).resolve().parent

def connector_module_available() -> bool:
    try:
        import importlib.util
        spec = importlib.util.find_spec("leaphub_connector")
        if spec is None:
            LOG.error("Módulo interno leaphub_connector não foi encontrado.")
            return False
        LOG.info("Módulo Connector disponível em %s.", spec.origin or "local desconhecido")
        return True
    except Exception as exc:  # noqa: BLE001
        LOG.error("Falha ao verificar módulo Connector: %s", exc)
        return False

CONNECTOR_MODULE_AVAILABLE = connector_module_available()
connector_options = write_connector_options()
beta_secret = str(OPTIONS.get("ocpp_beta_secret") or "").strip()
prod_secret = str(OPTIONS.get("ocpp_production_secret") or "").strip()
tunnel_token = str(OPTIONS.get("tunnel_token") or "").strip()
SERVICES: dict[str, ManagedService] = {
    "connector": ManagedService(
        "connector", "Connector Leapmotor", bool(OPTIONS.get("connector_enabled", True)),
        (secret_ok(OPTIONS.get("staging_secret")) or secret_ok(OPTIONS.get("production_secret"))) and CONNECTOR_MODULE_AVAILABLE,
        [sys.executable, "-u", str(APP_DIR / "connector_server.py")],
        {"LEAPHUB_OPTIONS_PATH": str(connector_options)},
        "http://127.0.0.1:8094/health",
    ),
    "ocpp_beta": ManagedService(
        "ocpp_beta", "OCPP Beta", bool(OPTIONS.get("ocpp_beta_enabled", True)), secret_ok(beta_secret),
        [sys.executable, "-u", str(APP_DIR / "ocpp_gateway.py")],
        ocpp_env("staging", 8092, str(OPTIONS.get("ocpp_beta_internal_url") or "").strip(), beta_secret, int(OPTIONS.get("ocpp_beta_max_connections") or 100)),
        "http://127.0.0.1:8092/health",
    ),
    "ocpp_production": ManagedService(
        "ocpp_production", "OCPP Produção", bool(OPTIONS.get("ocpp_production_enabled", False)), secret_ok(prod_secret),
        [sys.executable, "-u", str(APP_DIR / "ocpp_gateway.py")],
        ocpp_env("production", 8093, str(OPTIONS.get("ocpp_production_internal_url") or "").strip(), prod_secret, int(OPTIONS.get("ocpp_production_max_connections") or 100)),
        "http://127.0.0.1:8093/health",
    ),
    "tunnel": ManagedService(
        "tunnel", "Cloudflare Tunnel", bool(OPTIONS.get("tunnel_enabled", False)), secret_ok(tunnel_token, 40),
        [os.getenv("LEAPHUB_CLOUDFLARED", "/usr/local/bin/cloudflared"), "tunnel", "--no-autoupdate", "--loglevel", str(OPTIONS.get("tunnel_log_level") or "info"), "run"],
        {"TUNNEL_TOKEN": tunnel_token},
        None,
    ),
}



def telemetry_summary() -> dict[str, Any]:
    db_path = Path("/data/telemetry/telemetry.sqlite")
    if not db_path.is_file():
        return {"subscriptions": 0, "pending_events": 0, "status": "waiting"}
    try:
        import sqlite3
        with sqlite3.connect(db_path, timeout=2) as db:
            subscriptions = int(db.execute("SELECT COUNT(*) FROM subscriptions WHERE enabled=1").fetchone()[0])
            pending = int(db.execute("SELECT COUNT(*) FROM events WHERE status='pending'").fetchone()[0])
            failed = int(db.execute("SELECT COUNT(*) FROM events WHERE status='failed'").fetchone()[0])
            last = db.execute("SELECT MAX(last_success_at) FROM subscriptions").fetchone()[0]
            command_windows = 0
            try:
                command_windows = int(db.execute(
                    "SELECT COUNT(*) FROM subscriptions WHERE enabled=1 AND command_until>?",
                    (time.time(),),
                ).fetchone()[0])
            except sqlite3.DatabaseError:
                pass
            tracked = 0
            deduplicated = 0
            try:
                row = db.execute("SELECT COUNT(*), COALESCE(SUM(skipped_unchanged),0) FROM vehicle_state_cache").fetchone()
                tracked = int(row[0] or 0)
                deduplicated = int(row[1] or 0)
            except sqlite3.DatabaseError:
                pass
        return {
            "subscriptions": subscriptions,
            "pending_events": pending,
            "failed_events": failed,
            "tracked_vehicles": tracked,
            "deduplicated_events": deduplicated,
            "command_windows": command_windows,
            "last_success_at": last,
            "status": "active" if subscriptions else "waiting",
        }
    except Exception as exc:
        return {"subscriptions": 0, "pending_events": 0, "status": "degraded", "message": str(exc)[:160]}

def status_payload(include_logs: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "version": VERSION,
        "updated_at": utc_now(),
        "hostname_for_tunnel": "local-leaphub-gateway",
        "services": {},
        "telemetry": telemetry_summary(),
    }
    max_lines = max(20, min(300, int(OPTIONS.get("dashboard_log_lines") or 80)))
    for name, service in SERVICES.items():
        data = {
            "label": service.label,
            "enabled": service.enabled,
            "configured": service.configured,
            "state": service.state(),
            "pid": service.process.pid if service.process and service.process.poll() is None else None,
            "started_at": service.started_at,
            "restarts": service.restarts,
            "last_exit_code": service.last_exit_code,
            "health": service.health(),
        }
        if include_logs:
            data["logs"] = list(service.lines)[-max_lines:]
        result["services"][name] = data
    return result


def persist_status() -> None:
    temporary = STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(status_payload(False), ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATUS_PATH)


DASHBOARD_HTML = r'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Leap Hub Gateway</title><style>
:root{color-scheme:dark;--text:#f4f8ff;--muted:#9fb1c8;--accent:#24d4a3;--blue:#55a7ff;--warn:#ffc857;--line:rgba(255,255,255,.09)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#173657 0,transparent 38%),linear-gradient(150deg,#06101d,#09192b 55%,#06101d);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh}
main{max-width:1180px;margin:auto;padding:24px}.hero{display:flex;gap:18px;align-items:center;margin-bottom:20px}.mark{width:66px;height:66px;border-radius:20px;background:linear-gradient(145deg,var(--accent),var(--blue));display:grid;place-items:center;color:#05131d;font-weight:900;font-size:24px;box-shadow:0 14px 40px rgba(36,212,163,.22)}h1{margin:0;font-size:clamp(26px,4vw,42px)}.sub{color:var(--muted);margin:3px 0}.badge{margin-left:auto;padding:8px 12px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.04)}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.card{background:linear-gradient(150deg,rgba(18,36,58,.96),rgba(10,25,43,.96));border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 14px 42px rgba(0,0,0,.2)}.head{display:flex;gap:12px;align-items:flex-start}.head h2{margin:0;font-size:19px}.head p{margin:3px 0;color:var(--muted)}.state{margin-left:auto;border-radius:999px;padding:5px 9px;font-size:12px;font-weight:700}.running{background:rgba(36,212,163,.13);color:#64f0c5}.disabled{background:rgba(159,177,200,.12);color:var(--muted)}.needs_configuration,.stopped{background:rgba(255,200,87,.13);color:var(--warn)}
.meta{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0}.meta div{padding:10px;border-radius:12px;background:rgba(255,255,255,.035);color:var(--muted)}.meta strong{display:block;color:var(--text);font-size:14px}.actions{display:flex;flex-wrap:wrap;gap:8px}.btn{border:0;border-radius:11px;padding:9px 12px;background:linear-gradient(135deg,var(--accent),#36b7da);color:#06131e;font-weight:800;cursor:pointer}.btn.secondary{background:rgba(255,255,255,.07);color:var(--text);border:1px solid var(--line)}.btn:disabled{opacity:.45;cursor:not-allowed}
details{margin-top:12px}summary{cursor:pointer;color:var(--muted)}pre{white-space:pre-wrap;word-break:break-word;background:#050c15;border:1px solid var(--line);border-radius:12px;padding:12px;max-height:260px;overflow:auto;color:#bcd0e8;font-size:12px}.wide{grid-column:1/-1}.routes{display:grid;grid-template-columns:1fr auto;gap:8px}.routes code{background:#050c15;border:1px solid var(--line);border-radius:10px;padding:9px;overflow:auto}.notice{border-left:3px solid var(--blue);padding:10px 12px;background:rgba(85,167,255,.08);border-radius:10px;color:#cfe4ff}.foot{color:var(--muted);text-align:center;padding:20px}
@media(max-width:760px){main{padding:14px}.grid{grid-template-columns:1fr}.hero{align-items:flex-start}.badge{display:none}.meta{grid-template-columns:1fr 1fr}.routes{grid-template-columns:1fr}}
</style></head><body><main>
<div class="hero"><div class="mark">LH</div><div><h1>Leap Hub Gateway</h1><p class="sub">Telemetria resiliente, Connector, OCPP e Cloudflare em um único App</p></div><span class="badge">v1.11.83</span></div>
<div class="grid" id="cards"></div>
<section class="card wide" style="margin-top:16px"><div class="head"><div><h2>Rotas do Cloudflare Tunnel</h2><p>Como o Tunnel roda dentro do mesmo App, use 127.0.0.1 nas origens.</p></div></div><div class="routes"><code>connector.leaphub.com.br → http://127.0.0.1:8094</code><span>Connector</span><code>ocpp-beta.leaphub.com.br → http://127.0.0.1:8092</code><span>OCPP Beta</span><code>ocpp.leaphub.com.br → http://127.0.0.1:8093</code><span>Produção</span></div><p class="notice">A fila de telemetria sobrevive a reinícios do App. Uma queda do Home Assistant inteiro ainda cria uma lacuna real, que nunca será preenchida com dados inventados.</p></section>
<div class="foot">Tokens e chaves nunca são exibidos neste painel.</div></main><script>
const token='__TOKEN__';const labels={connector:'Connector Leapmotor',ocpp_beta:'OCPP Beta',ocpp_production:'OCPP Produção',tunnel:'Cloudflare Tunnel'};
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function action(name,kind){const b=document.querySelector(`[data-action="${name}-${kind}"]`);if(b)b.disabled=true;try{const r=await fetch(`api/services/${name}/${kind}`,{method:'POST',headers:{'X-LeapHub-UI-Token':token}});const j=await r.json();alert(j.message||'Concluído');await load()}catch(e){alert('Falha: '+e)}finally{if(b)b.disabled=false}}
function card(name,s){const health=s.health||{};const logs=(s.logs||[]).join('\n');return `<article class="card"><div class="head"><div><h2>${esc(labels[name]||s.label)}</h2><p>${s.configured?'Configuração pronta':'Configuração pendente'}</p></div><span class="state ${esc(s.state)}">${esc(s.state.replaceAll('_',' '))}</span></div><div class="meta"><div>Saúde<strong>${health.ok?'OK':'Atenção'}</strong></div><div>PID<strong>${esc(s.pid||'—')}</strong></div><div>Reinícios<strong>${esc(s.restarts)}</strong></div></div><div class="actions"><button class="btn" data-action="${name}-test" onclick="action('${name}','test')">Testar</button><button class="btn secondary" data-action="${name}-restart" onclick="action('${name}','restart')" ${!s.enabled||!s.configured?'disabled':''}>Reiniciar serviço</button></div><details><summary>Logs recentes</summary><pre>${esc(logs||'Sem logs nesta inicialização.')}</pre></details></article>`}
function telemetryCard(t){return `<article class="card"><div class="head"><div><h2>Telemetria contínua</h2><p>Sincronização ordenada, deduplicação e fila persistente</p></div><span class="state ${t.status==='active'?'running':'disabled'}">${esc(t.status||'waiting')}</span></div><div class="meta"><div>Veículos<strong>${esc(t.tracked_vehicles||0)}</strong></div><div>Pendentes<strong>${esc(t.pending_events||0)}</strong></div><div>Confirmação de comando<strong>${esc(t.command_windows||0)}</strong></div></div><p class="notice">Última coleta: ${esc(t.last_success_at||'aguardando veículo')} · Leituras repetidas evitadas: ${esc(t.deduplicated_events||0)} · Falhas permanentes: ${esc(t.failed_events||0)}</p></article>`}
async function load(){const r=await fetch('api/status',{cache:'no-store'});const j=await r.json();document.getElementById('cards').innerHTML=Object.entries(j.services).map(([n,s])=>card(n,s)).join('')+telemetryCard(j.telemetry||{})}
load();setInterval(load,5000);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "LeapHubGateway"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.debug("UI: " + fmt, *args)

    def common_headers(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'self'")

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.common_headers("application/json; charset=utf-8", len(raw))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            self.send_json(200, {"ok": True})
            return
        if path == "/api/status":
            self.send_json(200, status_payload(True))
            return
        if path == "/":
            raw = DASHBOARD_HTML.replace("__TOKEN__", UI_TOKEN).encode()
            self.send_response(200)
            self.common_headers("text/html; charset=utf-8", len(raw))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_json(404, {"ok": False})

    def do_POST(self) -> None:
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        if self.headers.get("X-LeapHub-UI-Token") != UI_TOKEN:
            self.send_json(403, {"ok": False, "message": "Ação recusada."})
            return
        if len(parts) != 4 or parts[:2] != ["api", "services"] or parts[2] not in SERVICES:
            self.send_json(404, {"ok": False, "message": "Ação não encontrada."})
            return
        service = SERVICES[parts[2]]
        action = parts[3]
        if action == "restart":
            if not service.enabled or not service.configured:
                self.send_json(409, {"ok": False, "message": "Serviço desativado ou sem configuração."})
                return
            service.stop(restart=True)
            self.send_json(202, {"ok": True, "message": f"Reinício solicitado para {service.label}."})
            return
        if action == "test":
            result = service.health(force=True)
            self.send_json(200 if result["ok"] else 503, {"ok": result["ok"], "message": f"{service.label}: {result['message']}"})
            return
        self.send_json(404, {"ok": False, "message": "Ação não encontrada."})


def serve_dashboard() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", int(os.getenv("LEAPHUB_DASHBOARD_PORT", "8099"))), Handler)
    server.daemon_threads = True
    LOG.info("Painel Ingress ouvindo na porta %s.", server.server_port)
    server.serve_forever()


def shutdown(*_: Any) -> None:
    if STOP.is_set():
        return
    STOP.set()
    for service in SERVICES.values():
        service.stop(False)


for signal_name in ("SIGTERM", "SIGINT"):
    sig = getattr(signal, signal_name, None)
    if sig is not None:
        signal.signal(sig, shutdown)

threading.Thread(target=serve_dashboard, daemon=True).start()
for service in SERVICES.values():
    if service.enabled and not service.configured:
        LOG.warning("%s está ativado, mas precisa de chave/token válido.", service.label)
    service.start()

while not STOP.wait(1.0):
    for service in SERVICES.values():
        service.supervise()
    persist_status()

persist_status()
LOG.info("Leap Hub Gateway encerrado.")
