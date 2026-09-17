"""Real localhost HTTP smoke test, with a private disposable AI DB and full business data."""
import json
import argparse
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
import httpx
import uvicorn

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
parser=argparse.ArgumentParser()
parser.add_argument('--provider',choices=['fake','business'],default='business')
parser.add_argument('--output',type=Path)
parser.add_argument('--llm-mode', choices=['live', 'offline'], default='live')
args=parser.parse_args()
with tempfile.TemporaryDirectory(prefix='ai-http-smoke-') as temporary:
    secret=secrets.token_urlsafe(48)
    os.environ['LLM_MODE'] = args.llm_mode
    os.environ.update(AI_SERVICE_DATABASE_URL='sqlite:///'+str(Path(temporary)/'smoke.db'),
        ERP_PROVIDER=args.provider,
        BUSINESS_DATASET_DB=os.environ.get('BUSINESS_DATASET_DB', str(ROOT/'data/business_24m.db')),
        AI_SERVICE_INTERNAL_TOKEN=secret,
        # Keep LLM_MODE/API keys from the pilot environment. The smoke test
        # must exercise the configured live provider when LLM_MODE=live;
        # compose/unit-test environments can still explicitly set offline.
        EMBEDDING_MODE='local',ENVIRONMENT='production' if args.provider=='business' else 'test')
    from main import app
    from app.api.security import signed_headers
    with socket.socket() as candidate:
        candidate.bind(('127.0.0.1',0)); port=candidate.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning',access_log=False))
    thread=threading.Thread(target=server.run,daemon=True); thread.start()
    output={}
    try:
        deadline=time.monotonic()+15
        while not server.started and time.monotonic()<deadline:
            if not thread.is_alive(): raise RuntimeError('HTTP server startup failed')
            time.sleep(.05)
        if not server.started: raise RuntimeError('HTTP server startup timed out')
        from app.data.factory import get_erp_provider
        selected_company=get_erp_provider().list_companies()[0]
        company=selected_company.id
        tenant=selected_company.tenant_id
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=75,trust_env=False) as client:
            def call(method,path,body=None,scope_tenant=tenant):
                req=client.build_request(method,path,json=body) if body is not None else client.build_request(method,path)
                req.headers.update(signed_headers(secret,method,req.url.raw_path.decode(),req.read(),
                    tenant_id=scope_tenant,company_id=company,actor='disposable-smoke-cfo',roles=['finance']))
                return client.send(req)
            assert client.get('/ready').status_code==200
            if args.provider == 'business':
                assert client.get('/docs').status_code == 404
                assert client.get('/redoc').status_code == 404
                assert client.get('/openapi.json').status_code == 404
            output['readiness']=200
            assert client.get(f'/api/v1/companies/{company}/thresholds').status_code==401
            output['unsigned_request']=401
            start,end=('2026-08-01','2026-08-31') if args.provider=='business' else ('2026-02-01','2026-02-28')
            response=call('POST','/api/v1/analysis/run',{'company_id':company,'period_start':start,'period_end':end})
            assert response.status_code==200,response.text
            anomalies=response.json(); assert anomalies
            output['anomalies']=len(anomalies)
            output['llm_mode'] = args.llm_mode
            output['acceptance_mode'] = 'real_provider' if args.llm_mode == 'live' else 'offline_not_acceptance'
            output['cards'] = []
            output['failures'] = []
            for anomaly in anomalies:
                result = call('POST', f"/api/v1/anomalies/{anomaly['id']}/generate-decision")
                if result.status_code != 200:
                    output['failures'].append({'anomaly_id': anomaly['id'], 'status': result.status_code, 'error': result.json()})
                    if result.json().get('error_code') == 'provider_rate_limited':
                        output['not_evaluated'] = len(anomalies) - len(output['cards']) - len(output['failures'])
                        break
                    continue
                generated = result.json()
                assert generated['generator'] == ('live_llm' if args.llm_mode == 'live' else 'fake_deterministic')
                assert generated['traceability']['anomaly_id'] == anomaly['id']
                assert generated['entity_id'] == anomaly['entity_ids'][0]
                assert generated['expected_impact'] == []
                assert generated['impact_assessment']['status'] == 'unavailable'
                assert generated['risks'] or generated['decision_readiness'] == 'blocked'
                output['cards'].append(generated)
            if output['failures']:
                output['passed'] = False
                output['health_after_failures'] = client.get('/health').status_code
                if args.output:
                    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
                print(json.dumps(output, indent=2, ensure_ascii=False))
                raise RuntimeError('Pilot acceptance failed; provider or card failures recorded')
            path=f"/api/v1/anomalies/{anomalies[0]['id']}/generate-decision"
            response=call('POST',path)
            assert response.status_code==200,response.text
            card=response.json()
            assert card['generator']==('live_llm' if args.llm_mode == 'live' else 'fake_deterministic')
            output['sample_card']=card
            assert call('POST',path).json()['id']==card['id']
            output['idempotent_generation']=True
            assert call('GET',f"/api/v1/decisions/{card['id']}/evidence",scope_tenant='wrong-tenant').status_code==404
            output['cross_tenant_access']=404
            approved=call('POST',f"/api/v1/decisions/{card['id']}/approve",{})
            assert approved.status_code==200,approved.text
            assert approved.json()['learning_status']=='completed'
            output['approval_learning']='completed'
            output['passed']=True
    finally:
        server.should_exit=True
        thread.join(timeout=10)
        if thread.is_alive(): raise RuntimeError('Owned HTTP smoke server did not stop')
if args.output:
    args.output.write_text(json.dumps(output,indent=2),encoding='utf-8')
print(json.dumps(output,indent=2))
