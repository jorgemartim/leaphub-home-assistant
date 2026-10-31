"""Real SDK wire signatures, synthetic HTTP only; never access a cloud account."""
import hashlib
import hmac
import json
import pytest
from leaphub_gateway.tests.test_charging_failure_1_12_132 import SDKClient, probe, BEGIN, END, VIN

def read(client):
    result=probe.probe_charging_history(client,vin=VIN,begin_ms=BEGIN+123,end_ms=END+123,
                                       page_num=2,request_profile="epoch_seconds")
    assert len(client.calls)==1 and client.last_api_results=={}
    assert VIN not in json.dumps(result) and 'private-' not in json.dumps(result)
    return result

def test_actual_sdk_signature_matches_exact_epoch_body():
    client=SDKClient();result=read(client);assert result['ok']
    _url,request=client.calls[0];body=request['json'];headers=request['headers']
    assert body==dict(vin=VIN,startTime=str(BEGIN//1000),endTime=str((END+1122)//1000),pageNum='2',pageSize='25')
    fields={key:headers[key] for key in ['acceptLanguage','channel','deviceId','deviceType','nonce','source','timestamp','version']}
    fields.update(body)
    expected=hmac.new(bytes(32),''.join(str(value)for _,value in sorted(fields.items())).encode(),hashlib.sha256).hexdigest()
    assert headers['sign']==expected and headers['token']=='private-token-sentinel'

def test_current_result_envelope_and_charge_interval_fields():
    client=SDKClient(body={'result':0,'data':{'list':[{'chargeEarliestTs':BEGIN+1000,'chargeLatestTs':END-1000,'chargeInEnergy':12.5,'chargeType':'FAST'}]}})
    result=read(client);assert result['ok']
    row=result['charging_history']['records'][0]
    assert row['charging_type']=='dc' and row['energy_kwh']==12.5 and row['started_at_ms']==BEGIN+1000

@pytest.mark.parametrize('envelope',[{'result':39},{'result':False,'data':{'list':[]}},{'code':0,'result':39,'data':{'list':[]}},{'code':39,'result':0,'data':{'list':[]}},{'result':0},{'data':{'list':[]}}])
def test_refusals_and_incomplete_envelopes_never_become_success(envelope):
    assert not read(SDKClient(body=envelope))['ok']

def test_explicit_empty_history_is_valid_without_manufacturing_records():
    result=read(SDKClient(body={'result':0,'data':{'list':[]}}))
    assert result['ok'] and result['charging_history']['records']==[]

def test_other_vehicle_is_excluded():
    result=read(SDKClient(body={'result':0,'data':{'list':[dict(vin='OTHER',chargeEarliestTs=BEGIN+1000,chargeLatestTs=END-1000,chargeInEnergy=1)]}}))
    assert result['ok'] and result['charging_history']['records']==[] and result['charging_history']['invalid_records']==1
