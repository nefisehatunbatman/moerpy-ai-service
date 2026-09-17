"""Startup and upgrade checks run in disposable databases only."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.rag.embeddings import LocalHashEmbedding
from app.rag.knowledge_base import KnowledgeBaseRepository
from app.rag.models import LearningReceipt, KnowledgeBaseEntry
from app.rag.migration import repair_global_learning
from app.decisions.repository import DecisionRepository
from app.tests.test_regressions import prepare, generate, FEB


@pytest.mark.parametrize('prefix', ['/', 'api/v1', '/api/v1/'])
def test_invalid_api_prefix_is_rejected(prefix):
    with pytest.raises(ValueError, match='API_PREFIX'):
        Settings(_env_file=None, ai_service_api_prefix=prefix)


def test_state_database_cannot_be_the_erp_database():
    with pytest.raises(ValueError, match='separate'):
        Settings(_env_file=None, erp_provider='postgres',
                 erp_database_url='postgresql://reader:read@database/business',
                 ai_service_database_url='postgresql+psycopg://writer:write@database:5432/business')


def test_postgres_configuration_requires_connection():
    with pytest.raises(ValueError, match='ERP_DATABASE_URL'):
        Settings(_env_file=None, erp_provider='postgres', erp_database_url=None)


def test_legacy_global_learning_moves_to_private_scope_and_is_idempotent(db_session):
    provider, _, _, anomaly = prepare(db_session)
    card = generate(db_session, provider, anomaly)
    record = DecisionRepository(db_session).get(card.id)
    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    template = kb.get('KB-0003')
    template.approval_count = 1
    template.usage_count = 1
    template.company_contexts = [record.company_id]
    db_session.add(LearningReceipt(decision_id=record.id, entry_id=template.id))
    db_session.commit()
    repair_global_learning(db_session)
    db_session.commit()
    receipt = db_session.get(LearningReceipt, record.id)
    private = kb.get(receipt.entry_id)
    assert private.id != template.id and private.tenant_id == record.tenant_id
    assert private.company_id == record.company_id and private.approval_count == 1
    assert template.company_contexts == [] and template.approval_count == 0
    repair_global_learning(db_session)
    db_session.commit()
    assert private.approval_count == 1


def test_empty_reanalysis_does_not_deactivate_another_tenant(db_session):
    from app.anomaly.repository import AnomalyRepository
    from app.anomaly.models import AnomalyRecord
    _, _, anomalies, _ = prepare(db_session)
    original = anomalies[0]
    foreign = original.model_copy(update={'id': 'foreign', 'tenant_id': 'other-tenant'})
    repo = AnomalyRepository(db_session)
    repo.save_all([foreign])
    repo.save_all([], original.company_id, FEB, original.tenant_id)
    assert repo.get('foreign').active
    assert repo.list_for_company(original.company_id) == []
    assert len(repo.list_for_company(original.company_id, tenant_id='other-tenant')) == 1


def test_mixed_scope_evidence_does_not_enter_decision(db_session):
    from app.evidence.builder import build_evidence
    from app.financial_impact.analyzer import analyze
    from app.thresholds.repository import ThresholdRepository
    _, kpis, _, anomaly = prepare(db_session)
    foreign = [k.model_copy(update={'tenant_id': 'other-tenant', 'value': 999999}) for k in kpis]
    impact = analyze(anomaly, foreign)
    evidence = build_evidence(anomaly, impact, foreign, ThresholdRepository(db_session).list_for_company('COMP-001'))
    assert impact.quantified_impact is None
    assert evidence.signals == []


def test_missing_availability_timestamp_is_not_known_cost():
    from app.data.providers.business_provider import available_at
    assert not available_at(None, FEB.end)
    assert not available_at('', FEB.end)
    assert not available_at('2026-03-01T00:00:00Z', FEB.end)
    assert available_at('2026-02-28T23:59:59Z', FEB.end)


def test_zero_business_cost_remains_a_verified_zero():
    from app.data.providers.business_provider import BusinessERPProvider
    provider = object.__new__(BusinessERPProvider)
    provider.metadata = {'dataset_id': 'test'}
    row = dict(invoice_line_id='line', selling_location_id='store', product_id='product',
               quantity_kg='1', net_amount_try='100', discount_amount_try='0', invoice_date='2026-02-01',
               cogs_try=0, cost_available_at='2026-02-01T00:00:00Z', tenant_id='tenant')
    provider.rows = lambda *args: [row]
    fact = provider.get_sales_facts('company', FEB)[0]
    assert fact.cogs_amount == 0 and fact.cost_basis_known


def test_future_month_end_is_not_treated_as_elapsed_days(client):
    from datetime import date, timedelta
    tomorrow = str(date.today() + timedelta(days=1))
    assert client.post('/api/v1/analysis/run', json={
        'company_id': 'COMP-001', 'period_start': '2026-02-01', 'period_end': tomorrow}).status_code == 422
    assert client.get('/api/v1/companies/COMP-001/kpis', params={
        'period_start': '2026-02-01', 'period_end': tomorrow}).status_code == 422


def test_business_period_cannot_extend_beyond_verified_dataset():
    from datetime import date
    from app.data.providers.business_provider import BusinessERPProvider
    from app.data.models import Period
    provider = object.__new__(BusinessERPProvider)
    provider.metadata = {'date_range': {'start': '2026-02-01', 'end': '2026-02-28'}}
    with pytest.raises(ValueError, match='coverage'):
        provider.get_sales_facts('company', Period(date(2026,2,1), date(2026,3,14)))
