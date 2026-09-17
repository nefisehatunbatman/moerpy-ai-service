"""Behavioral coverage for context-based, reviewable financial advice."""
import json
import pytest

from app.anomaly.schemas import Anomaly
from app.anomaly.repository import AnomalyRepository
from app.kpi.models import KpiResult, PeriodOut
from app.financial_impact.analyzer import analyze
from app.evidence.builder import build_evidence
from app.llm.client import LLMClient, FakeLLMClient
from app.llm.decision_generator import generate_decision, LLMOutputValidationError, NumberGroundingError
from app.decisions.service import generate_decision_for_anomaly
from app.rag.embeddings import LocalHashEmbedding


def inputs(metric='branch_margin_gap_pct'):
    period = PeriodOut(start='2026-02-01', end='2026-02-28')
    kpi = KpiResult.now(company_id='C', tenant_id='T', entity_type='branch', entity_id='S',
        metric=metric, value=15, unit='pp' if metric == 'branch_margin_gap_pct' else '%', period=period, source='verified_fixture', formula='fixture')
    anomaly = Anomaly(id='A', company_id='C', tenant_id='T', entity_type='branch', entity_ids=['S'],
        metric=metric, actual_value=15, threshold_value=10, deviation=5, severity='high',
        department='finance', period=period, detected_at='2026-02-28T00:00:00Z', run_id='run',
        kpi_snapshot=[kpi.model_dump()], threshold_snapshot=[])
    return anomaly, kpi


class AdviceClient(LLMClient):
    generator_name = 'test_context'

    def __init__(self, decision_type='PRICING'):
        self.decision_type = decision_type

    def generate(self, system_prompt, user_prompt):
        self.payload = json.loads(user_prompt.split('\n\n', 1)[1])
        return dict(title='Financial review', summary='Review the supplied evidence.',
            decision_type=self.decision_type, problem_signal='A threshold breach was reported.',
            recommended_decision='Consider reviewing pricing policy after checking product mix.',
            reasoning=['The cause is unverified and company constraints are missing.'],
            expected_impact=[dict(metric=self.payload['verified_evidence']['signals'][0]['metric'],
                direction='stabilize', type='qualitative')], department='finance', support_departments=[])


def test_margin_gap_does_not_prescribe_budget_reallocation():
    anomaly, kpi = inputs()
    impact = analyze(anomaly, [kpi])
    assert impact.decision_type is None
    assert impact.problem_type == 'branch_margin_difference'
    assert impact.financial_areas == ['profitability']
    assert 'cause_not_verified' in impact.information_gaps
    evidence = build_evidence(anomaly, impact, [kpi], [])
    client = AdviceClient()
    result = generate_decision(evidence, [], client)
    assert result.decision_type == 'FINANCIAL_RISK'
    assert result.expected_impact == []
    assert client.payload['verified_evidence']['decision_type'] is None
    assert 'PRICING' in client.payload['allowed_decision_types']


@pytest.mark.parametrize('language', ['tr', 'en'])
def test_unknown_metric_generates_review_card_and_is_idempotent(db_session, language):
    anomaly, kpi = inputs('unexpected_sales_drop')
    AnomalyRepository(db_session).save_all([anomaly])
    kwargs = dict(company_id='C', anomaly_id='A', erp_provider=None,
        llm_client=AdviceClient(), embedding_provider=LocalHashEmbedding(), language=language)
    card = generate_decision_for_anomaly(db_session, **kwargs)
    assert card.status == 'PROPOSED'
    assert card.assessment_status == 'review_required'
    assert card.decision_type == 'FINANCIAL_RISK'
    assert card.expected_impact == []
    assert card.observed_impact is None
    assert 'unmapped_financial_context' in card.information_gaps
    assert card.signals[0].value == kpi.value
    assert card.prompt_version == 'v5-executive-evidence'
    assert card.decision_readiness == 'blocked'
    assert generate_decision_for_anomaly(db_session, **kwargs).id == card.id


@pytest.mark.parametrize('change', [
    {'tenant_id': 'OTHER'}, {'company_id': 'OTHER'}, {'entity_id': 'OTHER'},
    {'entity_type': 'company'}, {'period': PeriodOut(start='2026-01-01', end='2026-01-31')},
    {'status': 'missing'}, {'unit': 'USD'}, {'value': None},
])
def test_financial_amount_requires_matching_valid_source(change):
    anomaly, kpi = inputs()
    companion = kpi.model_copy(update=dict(metric='branch_margin_gap_try', value=500, unit='TRY'))
    assert analyze(anomaly, [kpi, companion]).quantified_impact.value == 500
    assert analyze(anomaly, [kpi, companion.model_copy(update=change)]).quantified_impact is None


def test_no_evidence_does_not_trigger_model_call():
    anomaly, _ = inputs('unknown')
    evidence = build_evidence(anomaly, analyze(anomaly, []), [], [])
    client = AdviceClient()
    with pytest.raises(NumberGroundingError):
        generate_decision(evidence, [], client)
    assert not hasattr(client, 'payload')


def test_invalid_model_category_is_rejected():
    anomaly, kpi = inputs()
    evidence = build_evidence(anomaly, analyze(anomaly, [kpi]), [kpi], [])
    with pytest.raises(LLMOutputValidationError):
        generate_decision(evidence, [], AdviceClient('INVENTED_CATEGORY'))


def test_offline_unknown_metric_works_in_english():
    anomaly, kpi = inputs('unknown')
    evidence = build_evidence(anomaly, analyze(anomaly, [kpi]), [kpi], []).model_copy(update={'language': 'en'})
    assert generate_decision(evidence, [], FakeLLMClient()).decision_type == 'FINANCIAL_RISK'
