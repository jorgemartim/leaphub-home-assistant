"""Exercise the pinned SDK parser/HTTP transport, without cloud access or login."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
import requests
from leapmotor_api.client import LeapmotorApiClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import official_trip_probe as probe
BEGIN=1735698600000
END=1735702200000
VIN='TESTVIN0000000001'

def row():
    return {'chargeGunStartTs':BEGIN+1000,'chargeGunEndTs':END-1000,'chargeInEnergy':12.5,'chargeType':'2'}

class SDKClient(LeapmotorApiClient):
    def __init__(self,status=200,body=None,transport_error=False):
        self.device_id='synthetic';self.language='en-GB';self.timeout=4;self.verify_ssl=True
        self.base_url='https://synthetic.invalid';self.user_id='synthetic-user';self.token='private-token-sentinel'
        self.last_api_results={};self.calls=[]
        raw=json.dumps({'code':0,'data':{'list':[row()]}} if body is None else body) if not isinstance(body,str) else body
        def post(url,**kw):
            self.calls.append((url,kw))
            if transport_error:raise requests.ConnectionError('private-transport-sentinel')
            return SimpleNamespace(status_code=status,text=raw,headers={})
        self.session=SimpleNamespace(post=post)
    @property
    def sign_key(self):return bytes(32)
    @property
    def account_cert(self):return ('synthetic-cert','synthetic-key')
    def login(self):raise AssertionError('no login')
    def token_refresh(self):raise AssertionError('no refresh')
    def _ensure_token(self):raise AssertionError('no ensure-token')

def read(c):
    result=probe.probe_charging_history(c,vin=VIN,begin_ms=BEGIN,end_ms=END)
    assert len(c.calls)==1 and c.last_api_results=={}
    output=json.dumps(result)
    assert all(s not in output for s in [VIN,'private-','synthetic-user','synthetic-cert'])
    return result

def test_real_sdk_transport_and_parser_success():
    result=read(SDKClient());assert result['ok'] and result['charging_history']['records'][0]['energy_kwh']==12.5

@pytest.mark.parametrize('status,body,reason,temporary,code',[
 (200,{'code':40,'message':'private-message-sentinel','data':None},'charging_cloud_rejected',False,40),
 (403,{'code':40,'message':'private-message-sentinel'},'charging_access_denied',False,40),
 (401,{'code':100,'message':'private-message-sentinel'},'charging_auth_unavailable',True,100),
 (200,{'code':100,'message':'Token expired private-sentinel'},'charging_auth_unavailable',True,100),
 (429,{'code':429,'message':'private-message-sentinel'},'charging_cloud_temporary',True,429),
 (503,'<html>private-message-sentinel</html>','charging_cloud_temporary',True,None),
 (200,'<html>private-message-sentinel</html>','charging_response_invalid',False,None),
 (200,[],'charging_response_invalid',False,None),
 (200,{'code':0,'data':{'records':[]}},'charging_shape_unavailable',False,0),
 (200,{'code':'private-code-sentinel'},'charging_cloud_rejected',False,None),
 (400,{'code':True},'charging_cloud_rejected',False,None),
 (400,{'code':9999999999},'charging_cloud_rejected',False,None),
 (400,{'code':'-42'},'charging_cloud_rejected',False,-42),
])
def test_failure_categories_are_numeric_and_redacted(status,body,reason,temporary,code):
    r=read(SDKClient(status,body));assert not r['ok'] and r['reason']==reason and r['temporary'] is temporary
    assert r['diagnostic']['cloud_http_status']==status and r['diagnostic']['cloud_code']==code
    assert set(r['diagnostic'])=={'cloud_http_status','cloud_code','response_format','data_format','records_format'}
    assert 'charging_history' not in r
    if temporary:assert r['retry_after_seconds']==20

def test_real_sdk_transport_error_is_not_a_zero_or_login():
    r=read(SDKClient(transport_error=True));assert r['reason']=='charging_transport_error' and r['temporary']
    assert r['diagnostic']['cloud_http_status'] is None

def test_empty_cloud_history_still_requires_successful_protocol():
    r=read(SDKClient(body={'code':0,'data':{'list':[]}}));assert r['ok'] and r['charging_history']['records']==[]
    r=read(SDKClient(body={'code':40,'data':{'list':[]}}));assert not r['ok'] and 'charging_history'not in r
