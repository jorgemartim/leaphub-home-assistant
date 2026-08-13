from __future__ import annotations
import importlib.util, os, sqlite3, sys, tempfile, types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None: raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
connector = load("gw184_connector", ROOT / "leaphub_gateway" / "connector.py")
sys.modules["leaphub_connector"] = connector
orch = types.ModuleType("leaphub_connection_orchestrator"); orch.ORCHESTRATOR = object(); sys.modules["leaphub_connection_orchestrator"] = orch
evt = types.ModuleType("leaphub_event_transport"); evt.EVENT_TRANSPORT = object(); sys.modules["leaphub_event_transport"] = evt
telemetry = load("gw184_telemetry", ROOT / "leaphub_gateway" / "telemetry_engine.py")
checks=0; failures=[]
def check(cond,msg):
    global checks; checks+=1
    if not cond: failures.append(msg)
check(connector.CONNECTOR_VERSION == "1.12.84", "connector version")
expected={"lock","unlock","climate_on","climate_off","quick_cool","quick_heat","trunk_open","trunk_close","windows_open","windows_close","sunshade_open","sunshade_close"}
check(connector.ACK_FIRST_COMMANDS == expected, "ACK-first exacto")
src=(ROOT/'leaphub_gateway/telemetry_engine.py').read_text(encoding='utf-8')
con=(ROOT/'leaphub_gateway/connector.py').read_text(encoding='utf-8')
server=(ROOT/'leaphub_gateway/connector_server.py').read_text(encoding='utf-8')
check((ROOT/'leaphub_gateway/RELEASE_TARGET').read_text().strip()=="1.12.84", "release target")
check('TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0' in src, "teto 4s")
check('allow_slow_network=not (interactive or command_mode)' in src, "interactive pula slow network")
check('allow_slow_network\n                and not command_mode' in src, "slow_cycle condicionado")
check('include_secondary_network=False' in src, "imagem remota fora da trava")
check('return method(vehicle_id, params={"operate": "off"})' in con, "OFF C10")
check('repeat_exact_state_command' in con and 'command_attempts < 2' in con, "retry max 2")
check('announce_command_result_async(' in server, "anuncio imediato")
check('dispatched = bool(result.get("command_dispatched") or result.get("cloud_accepted"))' in src, "dispatch evidence")
check('self._supersede_pending_confirmations(' in src[src.index('    def _arm_command_confirmation('):src.index('    def _telemetry_request_timeout(') if '    def _telemetry_request_timeout(' in src[src.index('    def _arm_command_confirmation('):] else len(src)], "arm supersede")
# Testa diretamente a nova regra: comando posterior já confirmado ainda encerra janela anterior.
db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
db.execute('''CREATE TABLE command_confirmations (confirmation_id TEXT PRIMARY KEY,subscription_id TEXT,request_id TEXT,command_key TEXT,command_vehicle_id TEXT,context_json TEXT,started_at REAL,expires_at REAL,poll_count INTEGER DEFAULT 0,evaluated_samples INTEGER DEFAULT 0,stale_samples INTEGER DEFAULT 0,status TEXT,resolution TEXT,resolved_at REAL DEFAULT 0,created_at TEXT,updated_at TEXT)''')
class DummyDB:
    def __init__(self, conn): self.conn=conn
    def __enter__(self): return self.conn
    def __exit__(self,*a): return False
engine=telemetry.TelemetryEngine.__new__(telemetry.TelemetryEngine)
import threading
engine.lock=threading.RLock(); engine._db=lambda: DummyDB(db)
first,_=engine._register_confirmation(db,'sub','quick_cool','car','req-old','{}',180,1000.0,'2026-08-13T23:00:00Z')
result={'confirmation_pending':False,'command_dispatched':True,'cloud_accepted':True}
engine._arm_command_confirmation('sub', {'command':'climate_off','vehicle_id':'car','request_id':'req-new','parameters':{}}, result)
row=db.execute('SELECT status,resolution FROM command_confirmations WHERE confirmation_id=?',(first,)).fetchone()
check(row is not None and row['status']=='superseded', "direct-confirm supersede")
check(row is not None and row['resolution']=='superseded_by:climate_off', "direct-confirm resolution")
check(result.get('confirmation_armed_by_gateway') is False, "confirmed direct não arma nova janela")
if failures: raise SystemExit('Gateway 1.12.84 contract failed:\n- '+'\n- '.join(failures))
print({'ok':True,'checks':checks,'version':connector.CONNECTOR_VERSION})
