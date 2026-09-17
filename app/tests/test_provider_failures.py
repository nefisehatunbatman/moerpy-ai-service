import json
import httpx
import pytest
from app.llm.client import OpenAICompatibleLLMClient
from app.llm.transport import ProviderError
from app.rag.embeddings import OpenAICompatibleEmbedding

def test_provider_retry_uses_bounded_attempts(monkeypatch):
    attempts=[]
    def post(*args,**kwargs):
        attempts.append(kwargs['timeout'])
        return httpx.Response(429,request=httpx.Request('POST','https://provider.test'))
    monkeypatch.setattr(httpx,'post',post)
    monkeypatch.setattr('app.llm.transport.time.sleep',lambda _:None)
    with pytest.raises(ProviderError,match='budget'):
        OpenAICompatibleLLMClient('test','https://provider.test','test-model').generate('system','user')
    assert len(attempts)==3
    assert all(0<t<=20 for t in attempts)

def test_timeout_and_bad_json_are_controlled(monkeypatch):
    def timeout(*args,**kwargs): raise httpx.ReadTimeout('timeout')
    monkeypatch.setattr(httpx,'post',timeout)
    monkeypatch.setattr('app.llm.transport.time.sleep',lambda _:None)
    client=OpenAICompatibleLLMClient('test','https://provider.test','model')
    with pytest.raises(ProviderError): client.generate('system','user')
    monkeypatch.setattr(httpx,'post',lambda *a,**k:httpx.Response(200,json={'choices':[{'message':{'content':'not-json'}}]},request=httpx.Request('POST','https://provider.test')))
    with pytest.raises(ProviderError,match='malformed'): client.generate('system','user')

def test_embedding_shape_validation(monkeypatch):
    monkeypatch.setattr(httpx,'post',lambda *a,**k:httpx.Response(200,json={'data':[{'embedding':['bad',1]}]},request=httpx.Request('POST','https://provider.test')))
    with pytest.raises(ProviderError,match='embedding'):
        OpenAICompatibleEmbedding('test','https://provider.test','model').embed('text')

def test_raw_token_and_stale_context_are_rejected(client):
    from app.api.security import signed_headers
    from app.core.config import get_settings
    headers=signed_headers(get_settings().ai_service_internal_token,'GET','/api/v1/companies/COMP-001/thresholds',b'',
        tenant_id='fixture-tenant',company_id='COMP-001',actor='test',roles=['finance'],timestamp=1)
    assert client.get('/api/v1/companies/COMP-001/thresholds',headers=headers).status_code==401
    assert client.get('/api/v1/companies/COMP-001/thresholds',headers={'X-AI-Context':'','X-AI-Signature':''}).status_code==401

def test_english_decision_uses_english_labels(client):
    data=client.post('/api/v1/analysis/run',json={'company_id':'COMP-001','period_start':'2026-02-01','period_end':'2026-02-28'}).json()
    a=next(a for a in data if a['metric']=='working_capital_in_inventory_pct')
    response=client.post(f"/api/v1/anomalies/{a['id']}/generate-decision?language=en")
    assert response.status_code==200,response.text
    card=response.json()
    assert card['language']=='en'
    assert card['signals'][0]['label']=='Inventory to Revenue Ratio'
    assert card['expected_impact']==[]
    # Offline mode never claims tailored advice — it's a generic placeholder now that
    # a live model authors its own recommendation instead of echoing the reference catalog.
    assert card['recommended_decision'] == 'Verified evidence requires a scoped control.'
    assert card['decision_readiness'] == 'control_plan_only'
