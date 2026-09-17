"""Failure injection and contract tests; these are NOT live acceptance tests."""
from dataclasses import replace
from types import SimpleNamespace
import json
import pytest
from pydantic import ValidationError

from app.tests.test_financial_context import inputs, AdviceClient
from app.tests.test_llm_decision_generator import _evidence_and_retrieved
from app.tests.test_regressions import SmallProvider, sale, FEB
from app.financial_impact.analyzer import analyze
from app.evidence.builder import build_evidence
from app.decisions.executive import project
from app.decisions.service import generate_decision_for_anomaly, approve_decision, InvalidDecisionTransitionError
from app.anomaly.repository import AnomalyRepository
from app.anomaly.detector import detect_anomalies
from app.kpi.engine import compute_kpis
from app.rag.embeddings import LocalHashEmbedding
from app.core.errors import InvalidSourceDataError
from app.llm.decision_generator import generate_decision, NumberGroundingError


def test_unknown_evidence_survives_but_cannot_be_approved(db_session):
    anomaly, kpi = inputs('unknown_metric')
    AnomalyRepository(db_session).save_all([anomaly])
    card = generate_decision_for_anomaly(db_session, company_id='C', anomaly_id='A',
        erp_provider=None, llm_client=AdviceClient(), embedding_provider=LocalHashEmbedding())
    assert card.decision_readiness == 'blocked'
    assert card.confidence.score < 40
    assert card.traceability['anomaly_id'] == 'A'
    assert card.traceability['signals'][0]['value'] == kpi.value
    with pytest.raises(InvalidDecisionTransitionError):
        approve_decision(db_session, decision_id=card.id, actor='finance', note=None, embedding_provider=LocalHashEmbedding())


def test_context_from_another_anomaly_rejected():
    a, k = inputs()
    other = analyze(a, [k]).model_copy(update={'anomaly_id': 'OTHER'})
    with pytest.raises(InvalidSourceDataError):
        build_evidence(a, other, [k], [])


def test_missing_companion_blocks_control_and_preserves_observation():
    a, k = inputs()
    e = build_evidence(a, analyze(a, [k]), [k], [])
    assert e.assessment_status == 'review_required'
    p = project(e)
    assert p['decision_readiness'] == 'blocked'
    assert p['impact_assessment']['status'] == 'unavailable'
    assert p['success_metric']['target'] is None


@pytest.mark.parametrize('value', [None, '100', True, -1])
def test_invalid_required_value_has_controlled_source_error(value):
    with pytest.raises(InvalidSourceDataError):
        compute_kpis(SmallProvider([replace(sale('s', 10), revenue=value)]), 'C', FEB)


def test_empty_data_has_no_actionable_anomalies():
    kpis = compute_kpis(SmallProvider(), 'C', FEB)
    assert all(k.value is None for k in kpis)
    assert detect_anomalies('C', FEB, kpis, []) == []


def test_empty_entity_and_nan_rejected_before_analyzer():
    a, _ = inputs()
    for change in ({'entity_ids': []}, {'actual_value': float('nan')}):
        with pytest.raises(ValidationError):
            type(a).model_validate({**a.model_dump(), **change})


@pytest.mark.parametrize('claim', ['twenty days', 'yarıya düşür', '⅔ tasarruf', '² gün', 'yüzde beş'])
def test_numeric_variants_fail_closed(claim):
    a, k = inputs('unknown')
    e = build_evidence(a, analyze(a, [k]), [k], [])
    class Claim(AdviceClient):
        def generate(self, *args):
            raw = super().generate(*args)
            raw['recommended_decision'] = claim
            return raw
    with pytest.raises(NumberGroundingError):
        generate_decision(e, [], Claim())


@pytest.mark.parametrize('stage', ['analyze', 'build_evidence'])
def test_component_failure_is_isolated_request(client, monkeypatch, stage):
    from app.decisions import service
    anomaly = client.post('/api/v1/analysis/run', json=dict(company_id='COMP-001',
        period_start='2026-02-01', period_end='2026-02-28')).json()[0]
    original = getattr(service, stage)
    def broken(*args, **kwargs):
        raise RuntimeError('private-component-message')
    monkeypatch.setattr(service, stage, broken)
    response = client.post(f"/api/v1/anomalies/{anomaly['id']}/generate-decision")
    assert response.status_code == 500
    assert 'private-component-message' not in response.text
    assert client.get('/health').status_code == 200
    assert client.get('/api/v1/decisions?company_id=COMP-001').json() == []
    monkeypatch.setattr(service, stage, original)
    assert client.post(f"/api/v1/anomalies/{anomaly['id']}/generate-decision").status_code == 200


def test_threshold_absence_never_implies_normality_in_card():
    a, k = inputs('unknown')
    e = build_evidence(a, analyze(a, [k]), [k], [])
    assert project(e)['decision_readiness'] == 'blocked'


def test_model_may_author_its_own_action_beyond_the_catalog(db_session):
    # Real fixture pipeline so the required companion metric (unit_cost_variance_try) is
    # present -> assessment_status='context_available', so the review_required safety
    # override never fires and the model's own authored text survives untouched.
    e, retrieved = _evidence_and_retrieved('unit_cost_variance_pct', 'COMP-001', db_session)
    class Freeform(AdviceClient):
        generator_name = 'live_llm'
        def generate(self, *args):
            return {**super().generate(*args), 'action_id': 'freeze_orders',
                    'recommended_decision': 'Review purchasing exposure with finance before any commitment.'}
    output = generate_decision(e, retrieved, Freeform())
    assert output.action_id == 'freeze_orders'
    assert output.recommended_decision == 'Review purchasing exposure with finance before any commitment.'


@pytest.mark.parametrize('failure,status,code', [
    ('rate', 503, 'provider_rate_limited'), ('timeout', 504, 'provider_timeout'),
])
def test_provider_failure_leaves_anomaly_retryable(client, monkeypatch, failure, status, code):
    from app.llm.transport import ProviderRateLimitError, ProviderTimeoutError
    from app.llm.client import FakeLLMClient
    a = client.post('/api/v1/analysis/run', json=dict(company_id='COMP-001',
        period_start='2026-02-01', period_end='2026-02-28')).json()[0]
    def broken(*args):
        raise (ProviderRateLimitError if failure == 'rate' else ProviderTimeoutError)('secret')
    monkeypatch.setattr(FakeLLMClient, 'generate', broken)
    r = client.post(f"/api/v1/anomalies/{a['id']}/generate-decision")
    assert r.status_code == status and r.json()['error_code'] == code
    assert 'secret' not in r.text
    assert client.get('/health').status_code == 200
    assert client.get('/api/v1/decisions?company_id=COMP-001').json() == []


def test_partial_month_does_not_compare_inventory_ratio_to_monthly_policy():
    from datetime import date
    from app.data.models import InventoryFact, Period
    stock = InventoryFact('I', 'C', 'S', 'P', date(2026, 2, 15), 10, 5, tenant_id='fixture-tenant')
    k = compute_kpis(SmallProvider([sale('s', 5)], inventory=[stock]), 'C', Period(date(2026, 2, 1), date(2026, 2, 15)))
    ratio = next(x for x in k if x.metric == 'working_capital_in_inventory_pct')
    assert ratio.status == 'degraded'
    assert 'monthly_threshold_period_basis_unverified' in ratio.issues


def test_many_independent_anomalies_have_stable_bounded_evidence():
    from concurrent.futures import ThreadPoolExecutor
    def run(i):
        a, k = inputs('unknown')
        a = a.model_copy(update={'id': 'A'+str(i)})
        e = build_evidence(a, analyze(a, [k]), [k], [])
        return project(e)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(run, range(100)))
    assert len({x['traceability']['evidence_id'] for x in results}) == 100
    assert all(x['decision_readiness'] == 'blocked' for x in results)


def test_negative_baseline_percentage_uses_magnitude():
    from app.thresholds.engine import evaluate
    t = SimpleNamespace(operator='percentage_deviation', warning_value=10, critical_value=30, department='finance')
    result = evaluate(metric='test', entity_type='branch', entity_id='S', actual_value=-150, baseline_value=-100, threshold=t)
    assert result.status == 'critical'
