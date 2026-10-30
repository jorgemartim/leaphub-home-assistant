from __future__ import annotations
import json
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import connector
sys.modules.setdefault('leaphub_connector',connector)
import official_trip_probe as probe
sys.modules.setdefault('leaphub_official_trip_probe',probe)
from telemetry_engine import TelemetryEngine

BEGIN=int(datetime(2025,1,1,2,30,tzinfo=timezone.utc).timestamp()*1000)
END=BEGIN+3600000
VIN='TESTVIN0000000001'
assert len(VIN)==17

def row(a=BEGIN+1000,b=END-1000,kwh=12.5,kind='2'):
    return {'chargeGunStartTs':a,'chargeGunEndTs':b,'chargeInEnergy':kwh,'chargeType':kind,
            'chargeStartLongitude':'private-location-sentinel','vin':VIN,'token':'private-token-sentinel'}

class Client:
    sign_key=bytes(32);device_id='synthetic';language='en-GB';account_cert=('fake','fake');timeout=30
    def __init__(self,rows=None):self.rows=[row()] if rows is None else rows;self.calls=[];self.last_api_results={}
    def _auth_headers(self):return {'Authorization':'synthetic-only'}
    def _post_json(self,**kwargs):self.calls.append(kwargs);return {'status_code':200,'body':json.dumps({'data':{'list':self.rows}})}
    def _parse_api_body(self,status,body,label):self.last_api_results[label]={'message':'private-token-sentinel'};return json.loads(body)
    def login(self):raise AssertionError('login must not run')
    def token_refresh(self):raise AssertionError('refresh must not run')
    def _ensure_token(self):raise AssertionError('ensure-token must not run')


def read(client,**kwargs):return probe.probe_charging_history(client,vin=VIN,begin_ms=BEGIN,end_ms=END,**kwargs)

def test_exactly_one_signed_read_timezone_and_redaction():
    c=Client();result=read(c,page_num=2,utc_offset_minutes=-180)
    assert len(c.calls)==1
    req=c.calls[0];assert req['path']==probe.CHARGING_PATH
    assert req['json_body']=={'vin':VIN,'timeZone':'GMT-03:00','startTime':'2024-12-31','endTime':'2025-01-01','pageNum':2,'pageSize':25}
    assert req['headers']['Content-Type']=='application/json'
    assert result['charging_history']['records'][0]['energy_kwh']==12.5
    assert result['charging_history']['records'][0]['charging_type']=='dc'
    text=json.dumps(result);assert VIN not in text and 'private-' not in text
    assert c.last_api_results=={}

@pytest.mark.parametrize('page,offset',[(0,0),(6,0),(True,0),(1,841),(1,-721),(1,1),(1,True)])
def test_invalid_options_do_not_touch_cloud(page,offset):
    c=Client()
    with pytest.raises(ValueError):read(c,page_num=page,utc_offset_minutes=offset)
    assert c.calls==[]

def test_unknown_shape_is_not_empty_history():
    c=Client();c._post_json=lambda **kw:{'status_code':200,'body':'{"data":{}}'}
    assert read(c)['reason']=='charging_shape_unavailable'
    assert read(Client([]))['charging_history']['records']==[]

def test_records_are_bounded_validated_and_windowed():
    rows=[row(),row(),row(kwh=0,kind='1'),row(a=BEGIN-10000),row(a=END,b=END+1000),row(a=BEGIN-2000,b=BEGIN),row(kwh=-1),row(kwh='NaN'),row(kwh=True),'bad',row(kind='999',kwh=2)]
    r=read(Client(rows))['charging_history'];assert len(r['records'])==4
    assert r['invalid_records']==4 and r['out_of_window']==2
    assert any(x['crosses_window'] for x in r['records'])
    assert any(x['energy_kwh']==0 and x['charging_type']=='ac' for x in r['records'])
    assert any(x['charging_type']=='unknown' for x in r['records'])
    paged=read(Client([row(a=BEGIN+i,b=END-i) for i in range(30)]))['charging_history']
    assert len(paged['records'])<=25 and paged['has_more_possible'] and paged['response_truncated']

def test_no_parse_diagnostic_left_after_failure():
    c=Client()
    def failure(status,body,label):c.last_api_results[label]={'message':'private'};raise ValueError('synthetic failure')
    c._parse_api_body=failure
    assert read(c)['reason']=='charging_response_invalid'
    assert c.last_api_results=={}

@pytest.fixture
def engine(tmp_path):
    e=TelemetryEngine.__new__(TelemetryEngine);e.db_path=tmp_path/'test.sqlite'
    db=sqlite3.connect(e.db_path)
    db.executescript('CREATE TABLE account_auth_state(environment TEXT,account_id INTEGER,cooldown_until REAL,attempt_guard_until REAL);CREATE TABLE subscriptions(subscription_id TEXT,environment TEXT,account_id INTEGER,enabled INTEGER,updated_at TEXT,vehicle_ids_json TEXT);')
    db.execute('INSERT INTO subscriptions VALUES(?,?,?,?,?,?)',('sub','staging',9,1,'2025-01-01',json.dumps(['car-one'])));db.commit();db.close()
    e.session_lock=threading.RLock();e.session_locks_guard=threading.Lock();e.session_locks={}
    c=Client();e.sessions={'sub':{'client':c,'vehicles':[SimpleNamespace(car_id='car-one',vin=VIN)]}}
    e.operation_semaphore=threading.BoundedSemaphore(1);e.manual_pending_provider=lambda *a:False
    e.account_lock_provider=lambda *a:threading.RLock();e.telemetry_network_timeout_seconds=4.0
    return e,c

def payload():return {'account_id':9,'vehicle_id':'car-one','begintime_ms':BEGIN,'endtime_ms':END,'probe_kind':'charging_history','page_num':1,'utc_offset_minutes':-180}

def test_engine_dispatch_reuses_existing_authorized_session_and_restores_timeout(engine):
    e,c=engine;r=e.execute_driving_record_probe('staging',payload())
    assert r['ok'] and r['session_reused'] and r['probe_kind']=='charging_history'
    assert len(c.calls)==1 and c.timeout==30
    assert e.operation_semaphore.acquire(blocking=False);e.operation_semaphore.release()

def test_engine_manual_priority_never_touches_cloud(engine):
    e,c=engine;e.manual_pending_provider=lambda *a:True
    assert e.execute_driving_record_probe('staging',payload())['reason']=='manual_priority'
    assert c.calls==[]

def test_engine_wrong_environment_and_vehicle_never_fall_back_to_first(engine):
    e,c=engine
    with pytest.raises(ValueError):e.execute_driving_record_probe('production',payload())
    p=payload();p['vehicle_id']='foreign'
    with pytest.raises(ValueError):e.execute_driving_record_probe('staging',p)
    assert c.calls==[]

def test_engine_changed_subscription_and_unknown_kind_never_touches_cloud(engine):
    e,c=engine
    def invalidate(*args):
        db=sqlite3.connect(e.db_path);db.execute('UPDATE subscriptions SET enabled=0');db.commit();db.close();return threading.RLock()
    e.account_lock_provider=invalidate
    assert e.execute_driving_record_probe('staging',payload())['reason']=='subscription_changed'
    p=payload();p['probe_kind']='unknown'
    with pytest.raises(ValueError):e.execute_driving_record_probe('staging',p)
    assert c.calls==[]


def test_133_wait_and_response_format_are_logged_without_raw_values(engine,caplog):
    import logging
    from telemetry_engine import LOG
    e,c=engine;e.manual_pending_provider=lambda *a:True
    with caplog.at_level(logging.INFO,logger=LOG.name):
        assert e.execute_driving_record_probe('staging',payload())['reason']=='manual_priority'
    assert 'motivo=manual_priority'in caplog.text and c.calls==[]
    e.manual_pending_provider=lambda *a:False
    def html_response(**kw):
        c.calls.append(kw)
        return {'status_code':200,'body':'<html>private-response-sentinel</html>','headers':{'Content-Type':'text/html; private-header-sentinel'}}
    c._post_json=html_response
    with caplog.at_level(logging.INFO,logger=LOG.name):
        r=e.execute_driving_record_probe('staging',payload())
    assert not r['ok'] and 'formato=html'in caplog.text and 'tipo=html'in caplog.text
    assert 'private-'not in caplog.text and len(c.calls)==1 and c.timeout==30
