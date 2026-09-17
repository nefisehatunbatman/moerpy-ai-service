"""Build compact evidence with auditable, scope-safe context selection."""
from app.anomaly.schemas import Anomaly
from app.evidence.models import EvidencePackage, Signal, ThresholdSummary
from app.evidence.selection import select_context, SELECTION_VERSION
from app.evidence.policies import POLICY_REVISION, completeness
from app.financial_impact.models import FinancialImpact
from app.kpi.labels import label_for
from app.kpi.models import KpiResult
from app.thresholds.models import CompanyThreshold
from app.core.errors import InvalidSourceDataError


def build_evidence(anomaly: Anomaly, financial_impact: FinancialImpact,
                   kpi_results: list[KpiResult], thresholds: list[CompanyThreshold]) -> EvidencePackage:
    if financial_impact.anomaly_id != anomaly.id or financial_impact.metric != anomaly.metric:
        raise InvalidSourceDataError('Financial context does not belong to this anomaly')
    selection = select_context(anomaly, kpi_results, financial_impact.financial_areas)
    signals = [Signal(metric=k.metric, label=label_for(k.metric), value=k.value, unit=k.unit,
        formula=k.formula, entity_id=k.entity_id, entity_type=k.entity_type,
        selection_reason=reason, scope_relation=relation,
        source_ids=k.source_ids, source_count=k.source_count, source_digest=k.source_digest,
        coverage=k.coverage, issues=k.issues, snapshot_date=k.snapshot_date)
        for k, reason, relation in selection.selected]
    selected_kpis = [k for k, _, _ in selection.selected]
    gaps = set(financial_impact.information_gaps)
    if selection.policy is None:
        gaps.add('evidence_policy_missing')
    gaps.update('missing_context:' + metric for metric in selection.missing_required)
    if selection.omitted_count:
        gaps.add('context_limit_reached')
    if not signals:
        gaps.add('verified_anomaly_signal_missing')
    # An amount must also survive evidence validation; an invalid companion must
    # not remain as a separately presented quantified impact.
    quantified = financial_impact.quantified_impact
    if quantified and not any(s.metric == quantified.metric and s.value == quantified.value
                             and s.unit == quantified.unit and s.scope_relation == 'same_entity' for s in signals):
        quantified = None
        gaps.add('financial_amount_not_established')
    return EvidencePackage(
        anomaly_id=anomaly.id, company_id=anomaly.company_id,
        tenant_id=anomaly.tenant_id, entity_id=anomaly.entity_id,
        entity_type=anomaly.entity_type, run_id=anomaly.run_id,
        import_batch_ids=sorted({b for k in selected_kpis for b in k.import_batch_ids}),
        quality_issues=sorted({i for k in selected_kpis for i in k.issues}),
        problem_type=financial_impact.problem_type, financial_objective=financial_impact.financial_objective,
        decision_type=financial_impact.decision_type, financial_areas=financial_impact.financial_areas,
        information_gaps=sorted(gaps),
        assessment_status=financial_impact.assessment_status if signals and selection.policy and not selection.missing_required else 'review_required',
        context_selection_version=f'{SELECTION_VERSION}:{POLICY_REVISION}',
        evidence_policy=selection.policy,
        completeness_status=('unknown' if selection.policy is None else
                             'incomplete' if completeness(EvidencePackage.model_construct(
                                 evidence_policy=selection.policy, signals=signals,
                                 entity_type=anomaly.entity_type, entity_id=anomaly.entity_id)) < 1 else 'complete'),
        context_required_count=selection.required_count,
        context_present_required=selection.present_required,
        context_omitted_count=selection.omitted_count,
        context_exclusions=selection.exclusions,
        department=financial_impact.department, support_departments=financial_impact.support_departments,
        severity=anomaly.severity, period=anomaly.period, signals=signals,
        thresholds=[ThresholdSummary(metric=t.metric, operator=t.operator,
            warning_value=t.warning_value, critical_value=t.critical_value)
            for t in thresholds if t.metric == anomaly.metric],
        quantified_impact=quantified, causal_chain=financial_impact.causal_chain,
        causation_caveat=financial_impact.causation_caveat,
    )
