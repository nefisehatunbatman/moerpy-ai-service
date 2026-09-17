"""Deterministic financial context, not prescribed causes or actions."""
from dataclasses import dataclass
import logging
from app.anomaly.schemas import Anomaly
from app.financial_impact.models import FinancialImpact, QuantifiedImpact
from app.kpi.models import KpiResult

@dataclass(frozen=True)
class _Context:
    problem_type: str
    objective: str
    areas: tuple[str, ...]
    departments: tuple[str, ...]
    companion: str | None = None

_METRIC_CONTEXT = {
    'gross_margin_pct': _Context('margin_compression', 'protect_margin', ('profitability',), ('operations', 'procurement')),
    'branch_margin_gap_pct': _Context('branch_margin_difference', 'assess_profitability', ('profitability',), ('operations',), 'branch_margin_gap_try'),
    'unit_cost_variance_pct': _Context('unit_cost_overrun', 'protect_margin', ('cost', 'profitability'), ('procurement',), 'unit_cost_variance_try'),
    'days_inventory_outstanding': _Context('excess_inventory', 'improve_working_capital', ('inventory', 'working_capital'), ('operations',), 'inventory_value'),
    'working_capital_in_inventory_pct': _Context('cash_locked_in_inventory', 'improve_cash_flow', ('inventory', 'cash_flow'), ('operations', 'procurement'), 'inventory_value'),
    'waste_to_revenue_pct': _Context('waste_loss', 'protect_profitability', ('waste', 'profitability'), ('operations',), 'waste_value_try'),
}

def analyze(anomaly: Anomaly, kpi_results: list[KpiResult]) -> FinancialImpact:
    context = _METRIC_CONTEXT.get(anomaly.metric)
    gaps = ['cause_not_verified', 'company_objectives_and_constraints_not_supplied']
    if context is None:
        logging.getLogger(__name__).warning('unknown_anomaly_context', extra={'anomaly_id': anomaly.id})
        gaps.append('unmapped_financial_context')
        context = _Context('unmapped_financial_signal', 'assess_financial_relevance', (), ())
    scoped = [r for r in kpi_results if r.entity_id == anomaly.entity_id
              and r.entity_type == anomaly.entity_type and r.company_id == anomaly.company_id
              and r.tenant_id == anomaly.tenant_id and r.period == anomaly.period
              and r.status == 'ok' and r.value is not None]
    own = next((r for r in scoped if r.metric == anomaly.metric and r.value == anomaly.actual_value), None)
    if own is None:
        gaps.append('verified_anomaly_signal_missing')
    quantified = None
    companion = next((r for r in scoped if r.metric == context.companion and r.unit == 'TRY'), None)
    if own is not None and companion is not None:
        quantified = QuantifiedImpact(value=companion.value, unit=companion.unit, formula=companion.formula,
            metric=companion.metric, kind='scenario_impact' if companion.metric == 'branch_margin_gap_try' else 'observed_exposure')
    if quantified is None:
        gaps.append('financial_amount_not_established')
    return FinancialImpact(
        anomaly_id=anomaly.id, metric=anomaly.metric, problem_type=context.problem_type,
        financial_objective=context.objective, decision_type=None,
        financial_areas=list(context.areas), information_gaps=gaps,
        assessment_status='context_available' if own is not None and context.areas else 'review_required',
        department='finance', support_departments=list(context.departments),
        causal_chain=['Kaydedilmiş gösterge için eşik ihlali bildirilmiştir.'] if own is not None else [],
        quantified_impact=quantified,
        causation_caveat='Bu bulgu nedensellik kanıtı değildir. Gözlenen tutar veya senaryo etkisi beklenen tasarruf değildir.',
    )
