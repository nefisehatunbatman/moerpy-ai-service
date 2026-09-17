from datetime import date
import pytest

from app.tests.test_financial_context import inputs, AdviceClient
from app.evidence.builder import build_evidence
from app.evidence.selection import MAX_SIGNALS, select_context
from app.financial_impact.analyzer import analyze
from app.confidence.engine import _data_completeness
from app.llm.decision_generator import generate_decision
from app.evidence.policies import policy_for, POLICY_REVISION
from app.anomaly.detector import detect_anomalies
from app.anomaly.repository import AnomalyRepository
from app.data.models import Period
from app.thresholds.models import CompanyThreshold


def margin():
    a, k = inputs('gross_margin_pct')
    k = k.model_copy(update={'source_ids': ['sale:a'], 'import_batch_ids': ['main']})
    return a, k


def candidate(k, metric, **updates):
    return k.model_copy(update={'metric': metric, 'unit': 'TRY', 'value': 100, **updates})


def package(a, rows):
    return build_evidence(a, analyze(a, rows), rows, [])


def test_required_then_dynamic_provenance_and_domain_context():
    a, k = margin()
    rows = [k, candidate(k, 'revenue'), candidate(k, 'cogs'),
            candidate(k, 'new_discount_metric'),
            candidate(k, 'waste_value_try', source_ids=[]),
            candidate(k, 'unrelated', source_ids=[], import_batch_ids=['unrelated-batch'])]
    e = package(a, list(reversed(rows)))
    assert [(s.metric, s.selection_reason) for s in e.signals[:3]] == [
        ('gross_margin_pct', 'primary'), ('revenue', 'required_component'), ('cogs', 'required_component')]
    assert next(s for s in e.signals if s.metric == 'new_discount_metric').selection_reason == 'shared_source_records'
    assert next(s for s in e.signals if s.metric == 'waste_value_try').selection_reason == 'related_financial_area'
    assert 'unrelated' not in {s.metric for s in e.signals}
    assert 'unrelated-batch' not in e.import_batch_ids
    assert e.evidence_policy == policy_for('gross_margin_pct')
    assert e.context_selection_version.endswith(POLICY_REVISION)
    assert e.completeness_status == 'complete'
    assert e.model_dump() == package(a, rows).model_dump()


@pytest.mark.parametrize('change', [
    {'tenant_id':'foreign'}, {'company_id':'foreign'}, {'entity_id':'other'},
    {'entity_type':'company'}, {'period': inputs()[0].period.model_copy(update={'end':'2026-02-27'})},
    {'status':'degraded'}, {'value':None}, {'coverage':0}, {'unit':'USD'},
    {'snapshot_date':'2026-03-01'}, {'snapshot_date':'2020-01-01'},
])
def test_invalid_context_cannot_enter_evidence(change):
    a, k = margin()
    bad = candidate(k, 'revenue', import_batch_ids=['bad'], **change)
    e = package(a, [k, bad])
    assert [s.metric for s in e.signals] == ['gross_margin_pct']
    assert 'missing_context:revenue' in e.information_gaps
    assert 'bad' not in e.import_batch_ids


def test_conflicting_metric_excluded_and_primary_mismatch_blocks_generation():
    a, k = margin()
    revenue = candidate(k, 'revenue')
    e = package(a, [k, revenue, revenue.model_copy(update={'value':999})])
    assert 'missing_context:revenue' in e.information_gaps
    assert e.context_exclusions[0]['reason'] == 'duplicate_metric'
    assert package(a, [k.model_copy(update={'value':42}), revenue]).signals == []
    assert package(a, [k, k, revenue]).signals == []


def test_bounded_optional_context_does_not_hide_missing_components():
    a, k = margin()
    rows = [k] + [candidate(k, 'new_' + str(i)) for i in range(20)]
    e = package(a, rows)
    assert len(e.signals) == MAX_SIGNALS
    assert e.context_omitted_count == 13
    assert _data_completeness(e) == pytest.approx(1 / 3)
    assert 'missing_context:cogs' in e.information_gaps
    assert package(a, list(reversed(rows))).model_dump() == e.model_dump()


def test_unknown_metric_can_use_shared_provenance_without_semantic_guess():
    a, k = inputs('unknown_business_signal')
    k = k.model_copy(update={'source_ids':['event:a']})
    e = package(a, [k, candidate(k, 'unknown_related')])
    assert len(e.signals) == 2
    assert e.signals[1].selection_reason == 'shared_source_records'
    assert e.assessment_status == 'review_required'
    assert e.completeness_status == 'unknown'


def test_unknown_policy_has_zero_completeness_score():
    a, k = inputs('unknown_business_signal')
    e = package(a, [k])
    from app.confidence.engine import _data_completeness, _evidence_coverage
    assert _data_completeness(e) == 0.0
    assert _evidence_coverage(e) == 0.0


def test_parent_context_survives_detection_persistence_and_build(db_session):
    _, base = inputs('unit_cost_variance_pct')
    own = base.model_copy(update={'entity_type':'branch_product', 'entity_id':'S:P', 'value':25})
    amount = candidate(own, 'unit_cost_variance_try')
    parent = candidate(own, 'cogs', entity_type='branch', entity_id='S')
    foreign_parent = candidate(parent, 'revenue', entity_id='OTHER')
    sibling = candidate(own, 'cogs', entity_id='S:OTHER')
    threshold = CompanyThreshold(company_id='C', tenant_id='T', metric=own.metric,
        operator='greater_than', warning_value=10, critical_value=20, active=True, department='finance')
    anomalies = detect_anomalies('C', Period(date(2026,2,1),date(2026,2,28)),
        [own, amount, parent, foreign_parent, sibling], [threshold])
    AnomalyRepository(db_session).save_all(anomalies)
    restored = AnomalyRepository.to_schema(AnomalyRepository(db_session).get(anomalies[0].id))
    from app.kpi.models import KpiResult
    saved = [KpiResult.model_validate(k) for k in restored.kpi_snapshot]
    assert {(k.entity_type,k.entity_id) for k in saved} == {('branch_product','S:P'),('branch','S')}
    e = package(restored, saved)
    assert e.signals[0].metric == own.metric
    p = next(s for s in e.signals if s.metric == 'cogs')
    assert p.scope_relation == 'parent_branch'
    assert p.entity_id == 'S'
    assert e.quantified_impact.value == amount.value
    from app.decisions.service import generate_decision_for_anomaly
    from app.llm.client import FakeLLMClient
    from app.rag.embeddings import LocalHashEmbedding
    card = generate_decision_for_anomaly(db_session, company_id='C', anomaly_id=restored.id,
        erp_provider=None, llm_client=FakeLLMClient(), embedding_provider=LocalHashEmbedding())
    card_parent = next(s for s in card.signals if s.metric == 'cogs')
    assert card_parent.scope_relation == 'parent_branch'
    assert card_parent.entity_id == 'S'
    assert card_parent.value == parent.value


def test_parent_never_substitutes_missing_same_entity_component():
    a, k = inputs('unit_cost_variance_pct')
    a = a.model_copy(update={'entity_type':'branch_product','entity_ids':['S:P']})
    k = k.model_copy(update={'entity_type':'branch_product','entity_id':'S:P'})
    parent = candidate(k, 'unit_cost_variance_try', entity_type='branch', entity_id='S')
    e = package(a, [k,parent])
    assert 'missing_context:unit_cost_variance_try' in e.information_gaps
    assert e.quantified_impact is None
    assert next(s for s in e.signals if s.metric == parent.metric).scope_relation == 'parent_branch'


def test_parent_metric_cannot_be_used_as_product_expected_effect():
    from app.llm.schemas import LLMDecisionOutput
    from app.llm.decision_generator import verify_number_grounding
    a, k = inputs('unit_cost_variance_pct')
    a = a.model_copy(update={'entity_type':'branch_product','entity_ids':['S:P']})
    k = k.model_copy(update={'entity_type':'branch_product','entity_id':'S:P'})
    parent = candidate(k, 'cogs', entity_type='branch', entity_id='S')
    e = package(a, [k,parent])
    output = LLMDecisionOutput(title='Review', summary='Review', decision_type='FINANCIAL_RISK',
        problem_signal='Review', recommended_decision='Review', reasoning=['Review'],
        expected_impact=[dict(metric='cogs', direction='decrease', type='qualitative')])
    assert verify_number_grounding(output, e).expected_impact == []
