from __future__ import annotations
import importlib.util, os, sys, threading, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; MODULE=ROOT/'leaphub_gateway'/'ocpp_gateway.py'
def load(tmp_path):
    os.environ['LEAPHUB_RUNTIME_DIR']=str(tmp_path); os.environ['LEAPHUB_OCPP_STATE_DB']=str(tmp_path/'state.sqlite')
    sys.path.insert(0,str(ROOT/'leaphub_gateway'))
    spec=importlib.util.spec_from_file_location('ocpp_gateway_145_lock_test',MODULE); assert spec and spec.loader
    m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); return m
def test_parallel_reconnect_writes_do_not_lock(tmp_path):
    m=load(tmp_path); m.TARGETS_BY_NAME={'staging':m.ApiTarget('staging','https://example.invalid/ocpp','x'*32)}
    errors=[]
    def worker(i):
        try:
            for n in range(20):
                ident=f'CP-{i%4}'
                m.remember_route(ident,'staging'); m.remember_queue_owner('staging',ident,100+(i%4))
                m.queue_event(m.TARGETS_BY_NAME['staging'],ident,f'{i}-{n}','MeterValues',{'x':n},'test')
        except BaseException as exc: errors.append(exc)
    threads=[threading.Thread(target=worker,args=(i,)) for i in range(12)]
    [x.start() for x in threads]; [x.join(15) for x in threads]
    assert not errors
    with m.state_db() as db:
        assert db.execute('SELECT COUNT(*) FROM routes').fetchone()[0] == 4
        assert db.execute('SELECT COUNT(*) FROM queue_owners').fetchone()[0] == 4
        assert db.execute('SELECT COUNT(*) FROM event_queue').fetchone()[0] == m.EVENT_QUEUE_MAX
    d=m.queue_diagnostics(); assert d['sqlite_single_writer'] is True; assert d['sqlite_lock_failures']==0
def test_reconnect_diagnostics_are_aggregate(tmp_path):
    m=load(tmp_path)
    for _ in range(m.RECONNECT_STORM_THRESHOLD+1): m.record_reconnect('SECRET-CP')
    d=m.reconnect_diagnostics(); assert d['storm_wallboxes']==1; assert d['max_reconnects_single_wallbox']>=m.RECONNECT_STORM_THRESHOLD
    assert 'SECRET-CP' not in repr(d)
