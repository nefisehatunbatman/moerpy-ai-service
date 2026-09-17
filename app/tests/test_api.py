def run(client):
    return client.post('/api/v1/analysis/run',json={'company_id':'COMP-001','period_start':'2026-02-01','period_end':'2026-02-28'})

def test_health(client):
    assert client.get('/health').json()=={'status':'ok'}

def test_full_http_flow(client):
    response=run(client)
    assert response.status_code==200,response.text
    anomaly=next(a for a in response.json() if a['metric']=='working_capital_in_inventory_pct')
    generated=client.post(f"/api/v1/anomalies/{anomaly['id']}/generate-decision")
    assert generated.status_code==200,generated.text
    card=generated.json()
    assert card['status']=='PROPOSED'
    assert card['observed_impact']['value']==492000
    assert card['expected_impact']==[]  # Offline mode does not predict an effect.
    assert card['assessment_status']=='context_available'
    assert 'company_objectives_and_constraints_not_supplied' in card['information_gaps']
    assert card['company_id']=='COMP-001'
    repeated=client.post(f"/api/v1/anomalies/{anomaly['id']}/generate-decision")
    assert repeated.json()['id']==card['id']
    approved=client.post(f"/api/v1/decisions/{card['id']}/approve",json={'actor':'forged-user'})
    assert approved.status_code==200,approved.text
    assert approved.json()['learning_status']=='completed'
    lifecycle=client.get(f"/api/v1/decisions/{card['id']}/lifecycle").json()
    assert [e['to_status'] for e in lifecycle]==['GENERATING','PROPOSED','APPROVED']
    assert lifecycle[-1]['actor']=='test-cfo'
    assert client.post(f"/api/v1/decisions/{card['id']}/approve",json={}).status_code==409

def test_threshold_put_overrides_and_lists_disabled(client):
    response=client.put('/api/v1/companies/COMP-001/thresholds',json={'metric':'gross_margin_pct','operator':'less_than','warning_value':99,'critical_value':1,'active':False})
    assert response.status_code==200,response.text
    rows=client.get('/api/v1/companies/COMP-001/thresholds').json()
    assert len(rows)==6
    assert next(r for r in rows if r['metric']=='gross_margin_pct')['active'] is False

def test_get_nonexistent_decision_returns_404(client):
    assert client.get('/api/v1/decisions/missing').status_code==404

def test_cross_company_record_access_blocked(client):
    anomaly=run(client).json()[0]
    card=client.post(f"/api/v1/anomalies/{anomaly['id']}/generate-decision").json()
    client.company_id='COMP-002'
    for suffix in ('','/evidence','/rag-context','/lifecycle'):
        assert client.get(f"/api/v1/decisions/{card['id']}"+suffix).status_code==404
    for suffix in ('approve','reject','retry-learning'):
        assert client.post(f"/api/v1/decisions/{card['id']}/{suffix}",json={}).status_code==404
    assert client.post(f"/api/v1/anomalies/{anomaly['id']}/generate-decision").status_code==404

def test_same_company_wrong_tenant_blocked(client):
    client.tenant_id='another-tenant'
    assert run(client).status_code==404

def test_non_finance_cannot_change_policy(client):
    client.roles=['user']
    assert client.put('/api/v1/companies/COMP-001/thresholds',json={'metric':'gross_margin_pct','operator':'less_than','warning_value':30,'critical_value':20}).status_code==403

def test_invalid_inputs_rejected(client):
    assert client.put('/api/v1/companies/COMP-001/thresholds',json={'metric':'gross_margin_pct','operator':'invalid','warning_value':30,'critical_value':20}).status_code==422
    assert client.get('/api/v1/companies/COMP-001/kpis',params={'period_start':'2026-02-28','period_end':'2026-02-01'}).status_code==422
    assert client.post('/api/v1/analysis/run',json={'company_id':'MISSING','period_start':'2026-02-01','period_end':'2026-02-28'}).status_code==404

def test_invalid_signature_rejected(client):
    assert client.get('/api/v1/companies/COMP-001/thresholds',headers={'X-AI-Signature':'wrong'}).status_code==401
