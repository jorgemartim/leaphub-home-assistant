"""Contrato 1.12.55/1.12.91 — `engine_precheck_ms` precisa ser quebrável e bounded.

A 1.12.55 colocou teto na trava global para impedir esperas de minutos. Em
14/08/2026 a 1.12.90 isolou o restante do defeito: `trava_motor=12292ms` com
`latência_conta=1ms` e `dispatch=612ms`, além de duas recusas no teto de 20s.
A 1.12.91 preserva a intenção do contrato removendo a dependência da trava
global no SELECT somente-leitura e limitando o próprio SQLite.
"""
from __future__ import annotations
import ast
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
_RELEASE_TARGET=(ROOT/"leaphub_gateway"/"RELEASE_TARGET").read_text(encoding="utf-8").strip()
APP=ROOT/"leaphub_gateway"
ENGINE=(APP/"telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR=(APP/"connector.py").read_text(encoding="utf-8")
SERVER=(APP/"connector_server.py").read_text(encoding="utf-8")
SUBPHASES=("auth_status_ms","engine_lock_wait_ms","subscription_read_ms")
def execute_command_body():
    tree=ast.parse(ENGINE)
    for node in ast.walk(tree):
        if isinstance(node,ast.FunctionDef) and node.name=="execute_command": return ast.get_source_segment(ENGINE,node) or ""
    raise AssertionError("execute_command desapareceu do motor")
def test_engine_publishes_the_three_subphases():
    for field in SUBPHASES: assert f'phase["{field}"] = {field}' in ENGINE,field
def test_auth_status_is_measured_before_subscription_read():
    started=ENGINE.index("engine_started = time.monotonic()")
    auth=ENGINE.index("auth_status_ms = int(round((time.monotonic() - engine_started) * 1000))")
    read=ENGINE.index("subscription_read_started = time.monotonic()",auth)
    assert started < auth < read
def test_command_precheck_does_not_acquire_global_engine_lock():
    body=execute_command_body(); assert "self.lock.acquire(" not in body; assert "with self.lock" not in body
    assert "engine_lock_wait_ms = 0" in body
    assert "self._db(timeout_seconds=COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS)" in body
def test_subscription_read_timeout_is_short_and_explicit():
    m=re.search(r"^COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS = ([0-9.]+)$",ENGINE,re.MULTILINE); assert m
    assert 0.1 <= float(m.group(1)) <= 2.0
def test_sqlite_busy_is_temporary_and_pre_dispatch():
    body=execute_command_body(); assert "except sqlite3.OperationalError as exc:" in body
    assert 'if "locked" in message or "busy" in message:' in body
    assert "A fila local de telemetria não liberou a leitura de assinatura a tempo." in body
    assert "O comando não foi enviado ao veículo e continua na fila." in body
    assert "except connector.ConnectorTemporaryError as exc:" in SERVER
def test_session_serialization_is_preserved():
    body=execute_command_body(); assert "with self._session_operation_lock(subscription_id):" in body
    assert 'with self._dispatch_timeout(session["client"]):' in body
def test_subphases_reach_server_latency_and_log():
    for field in SUBPHASES: assert f'"{field}": int(phase_latency.get("{field}") or 0),' in SERVER,field
    for label in ("status_conta=%sms","trava_motor=%sms","leitura_assinatura=%sms"): assert label in SERVER,label
def test_subphases_do_not_double_count_in_unaccounted():
    u=SERVER[SERVER.index('"unaccounted_ms": max(0,'):]; u=u[:u.index("))")]
    for field in SUBPHASES: assert field not in u,field
def test_log_line_placeholders_match_its_arguments():
    tree=ast.parse(SERVER); checked=0
    for node in ast.walk(tree):
        if not (isinstance(node,ast.Call) and node.args): continue
        first=node.args[0]
        if not (isinstance(first,ast.Constant) and isinstance(first.value,str)): continue
        if "Comando remoto %s finalizado no worker" not in first.value: continue
        checked+=1; assert first.value.count("%s")==len(node.args)-1
    assert checked==1
def test_version_follows_the_release():
    assert f'ENGINE_VERSION = "{_RELEASE_TARGET}"' in ENGINE
    assert f'CONNECTOR_VERSION = "{_RELEASE_TARGET}"' in CONNECTOR
