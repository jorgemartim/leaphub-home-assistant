from __future__ import annotations
import importlib.util, os, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/'leaphub_gateway'/'ocpp_gateway.py'
def load(tmp_path):
    os.environ['LEAPHUB_RUNTIME_DIR']=str(tmp_path)
    os.environ['LEAPHUB_OCPP_STATE_DB']=str(tmp_path/'state.sqlite')
    sys.path.insert(0,str(ROOT/'leaphub_gateway'))
    spec=importlib.util.spec_from_file_location('ocpp_gateway_rr_144',MODULE); assert spec and spec.loader
    m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); return m
def setup(m):
    target=m.ApiTarget('staging','https://example.invalid/ocpp','x'*32); m.TARGETS_BY_NAME={'staging':target}; return target
def add_event(m, identity, mid, owner):
    m.remember_queue_owner('staging',identity,owner); now=time.time()
    with m.state_db() as db:
        db.execute("INSERT INTO event_queue(target_name,identity,message_id,ocpp_action,payload_json,attempts,available_at,created_at,last_error) VALUES('staging',?,?, 'MeterValues','{}',0,?,?,NULL)",(identity,mid,now-1,now)); db.commit()
def add_result(m, identity, cid, owner):
    m.remember_queue_owner('staging',identity,owner); now=time.time()
    with m.state_db() as db:
        db.execute("INSERT INTO command_result_queue(target_name,identity,command_id,status,payload_json,error_text,attempts,available_at,created_at,last_error) VALUES('staging',?,?,'completed','{}','',0,?,?,NULL)",(identity,cid,now-1,now)); db.commit()
def test_more_than_batch_size_rotates_to_next_users(tmp_path):
    m=load(tmp_path); setup(m)
    for i in range(40): add_event(m,f'CP-{i:02d}',f'm-{i:02d}',1000+i)
    seen=[]; m.api_call=lambda _t,p,_timeout: seen.append(p['identity']) or {}
    assert m.replay_queue_once(25)==25
    first=set(seen); assert len(first)==25
    assert m.replay_queue_once(15)==15
    second=set(seen[25:]); assert len(second)==15
    assert first.isdisjoint(second)
def test_cursor_survives_module_level_scheduler_state(tmp_path):
    m=load(tmp_path); setup(m)
    for i in range(3): add_event(m,f'CP-{i}',f'm-{i}',200+i)
    m.api_call=lambda _t,p,_timeout: {}
    m.replay_queue_once(1)
    cursor,turns=m._scheduler_state('event')
    assert cursor and turns==1
    with m.state_db() as db:
        assert db.execute("SELECT COUNT(*) FROM queue_scheduler_state WHERE queue_kind='event'").fetchone()[0]==1
def test_command_results_use_same_persistent_rotation(tmp_path):
    m=load(tmp_path); setup(m)
    for i in range(30): add_result(m,f'CR-{i:02d}',i+1,3000+i)
    seen=[]; m.api_call=lambda _t,p,_timeout=8.0: seen.append(p['identity']) or {}
    assert m.replay_command_results_once(25)==25
    assert m.replay_command_results_once(5)==5
    assert len(set(seen))==30
def test_diagnostics_do_not_expose_cursor_identity(tmp_path):
    m=load(tmp_path); setup(m); add_event(m,'SECRET-CP','m1',987654)
    m.api_call=lambda _t,p,_timeout: {}
    m.replay_queue_once(1)
    d=m.queue_diagnostics()
    assert d['fairness_cursor_persistent'] is True
    assert d['fairness_strategy']=='persistent_round_robin'
    assert d['event_owner_turns']>=1
    assert 'SECRET-CP' not in repr(d) and '987654' not in repr(d)
