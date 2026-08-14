from __future__ import annotations
import contextlib
import importlib.util
import sqlite3
import sys
import threading
import time
import types
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/"leaphub_gateway"
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path); assert spec and spec.loader
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module
connector=load("leaphub_connector_191",APP/"connector.py"); sys.modules.setdefault("leaphub_connector",connector)
_prev_o=sys.modules.get("leaphub_connection_orchestrator"); _prev_e=sys.modules.get("leaphub_event_transport")
try:
    orch=types.ModuleType("leaphub_connection_orchestrator"); orch.ORCHESTRATOR=object(); sys.modules["leaphub_connection_orchestrator"]=orch
    event=types.ModuleType("leaphub_event_transport"); event.EVENT_TRANSPORT=object(); sys.modules["leaphub_event_transport"]=event
    telemetry=load("gw191_telemetry",APP/"telemetry_engine.py")
finally:
    if _prev_o is None: sys.modules.pop("leaphub_connection_orchestrator",None)
    else: sys.modules["leaphub_connection_orchestrator"]=_prev_o
    if _prev_e is None: sys.modules.pop("leaphub_event_transport",None)
    else: sys.modules["leaphub_event_transport"]=_prev_e
class _Result:
    def __init__(self,row): self.row=row
    def fetchone(self): return self.row
class _Db:
    def __init__(self,row=None): self.row=row
    def execute(self,*_args,**_kwargs): return _Result(self.row)
def bare_engine():
    engine=telemetry.TelemetryEngine.__new__(telemetry.TelemetryEngine)
    engine.lock=threading.Lock(); engine.assert_account_cloud_allowed=lambda *_a,**_k: None
    engine._execute_isolated_command=lambda *_a,**_k: {"ok":True,"isolated":True}
    return engine
def test_global_engine_lock_held_does_not_delay_command_precheck():
    engine=bare_engine(); engine.lock.acquire(); seen=[]
    @contextlib.contextmanager
    def fake_db(timeout_seconds=30.0): seen.append(timeout_seconds); yield _Db(row=None)
    engine._db=fake_db; started=time.monotonic(); result=engine.execute_command("staging",{"account_id":1},None); elapsed=time.monotonic()-started
    assert result=={"ok":True,"isolated":True}; assert elapsed < 0.20,elapsed
    assert engine.lock.locked(); assert seen==[telemetry.COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS]
def test_busy_subscription_read_fails_temporary_before_dispatch():
    engine=bare_engine(); engine.lock.acquire()
    @contextlib.contextmanager
    def busy_db(timeout_seconds=30.0):
        assert timeout_seconds==telemetry.COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS
        raise sqlite3.OperationalError("database is locked")
        yield
    engine._db=busy_db
    with pytest.raises(telemetry.connector.ConnectorTemporaryError,match="leitura de assinatura"):
        engine.execute_command("staging",{"account_id":1},None)
    assert engine.lock.locked()
def test_command_path_still_serializes_the_shared_session():
    source=(APP/"telemetry_engine.py").read_text(encoding="utf-8")
    start=source.index("def execute_command(")
    end=source.index("    @contextlib.contextmanager\n    def _telemetry_request_timeout",start)
    body=source[start:end]
    assert "with self._session_operation_lock(subscription_id):" in body
    assert 'with self._dispatch_timeout(session["client"]):' in body
    assert "_TelemetryOneShotClient" not in source
