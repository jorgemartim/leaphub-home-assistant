from __future__ import annotations
import importlib.util, os, sys, tempfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; APP=ROOT/'leaphub_gateway'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path); assert spec and spec.loader
    m=importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m
def test_async_sync_journal_finishes_without_blocking_request(tmp_path):
    os.environ['LEAPHUB_OPTIONS_PATH']=str(tmp_path/'options.json'); (tmp_path/'options.json').write_text('{"staging_secret":"'+'x'*32+'","connector_max_parallel":2}')
    os.environ['LEAPHUB_COMMAND_DB_PATH']=str(tmp_path/'commands.sqlite'); os.environ['LEAPHUB_NONCE_DB_PATH']=str(tmp_path/'nonces.sqlite'); os.environ['LEAPHUB_TELEMETRY_DIR']=str(tmp_path/'telemetry')
    load('leaphub_privacy',APP/'privacy.py'); load('leaphub_connection_orchestrator',APP/'connection_orchestrator.py'); load('leaphub_event_transport',APP/'event_transport.py'); load('leaphub_connector',APP/'connector.py'); load('leaphub_telemetry_engine',APP/'telemetry_engine.py')
    s=load('connector_server_sync_145',APP/'connector_server.py'); s.initialize_command_db()
    s.TELEMETRY.execute_account_operation=lambda env,payload,sync,origin: {'ok':True,'vehicles':[{'remote_id':'V1'}]}
    payload={'request_id':'sync-1234567890abcdef','account_id':7,'vehicle_id':'V1','credentials':{'email':'x','password':'y'}}
    key,replay=s.sync_journal_begin('staging',payload); assert key and replay is None
    started=time.monotonic(); assert s.start_sync_job('staging',payload,key,payload['request_id']) is True
    assert time.monotonic()-started < 0.5
    deadline=time.time()+5
    while time.time()<deadline:
        status=s.sync_journal_status('staging',{'request_id':payload['request_id']})
        if status.get('status')=='completed': break
        time.sleep(0.02)
    assert status['status']=='completed'; assert status['vehicles'][0]['remote_id']=='V1'; assert status['sync_pending'] is False
