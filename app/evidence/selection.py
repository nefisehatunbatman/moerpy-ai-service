"""Bounded evidence selection from verified, same-run KPI snapshots.

Relationships are explicit policy; formulas and labels are never parsed as code.
Shared provenance means related evidence, not causation or extra independent proof.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
import math

from app.core.config import get_settings
from app.kpi.models import KpiResult
from app.evidence.policies import EvidencePolicy, policy_for, EXPLORATORY_MAX_SIGNALS

SELECTION_VERSION = 'context-v2-policy'
MAX_SIGNALS = EXPLORATORY_MAX_SIGNALS  # Compatibility alias; known metrics use their policy budget.


@dataclass(frozen=True)
class MetricContext:
    areas: tuple[str, ...]
    unit: str | None = None


# Semantic descriptions, not exhaustive per-anomaly context lists. New metrics
# may participate through shared source IDs even without a catalog entry.
CATALOG = {
    'revenue': MetricContext(('profitability', 'cash_flow'), unit='TRY'),
    'cogs': MetricContext(('profitability', 'cost'), unit='TRY'),
    'gross_profit': MetricContext(('profitability',), 'TRY'),
    'gross_margin_pct': MetricContext(('profitability',), '%'),
    'branch_margin_gap_pct': MetricContext(('profitability',), 'pp'),
    'branch_margin_gap_try': MetricContext(('profitability',), unit='TRY'),
    'unit_cost_variance_pct': MetricContext(('cost', 'profitability'), '%'),
    'unit_cost_variance_try': MetricContext(('cost', 'profitability'), unit='TRY'),
    'inventory_value': MetricContext(('inventory', 'working_capital', 'cash_flow'), unit='TRY'),
    'days_inventory_outstanding': MetricContext(('inventory', 'working_capital'), 'days'),
    'working_capital_in_inventory_pct': MetricContext(('inventory', 'cash_flow'), '%'),
    'waste_value_try': MetricContext(('waste', 'profitability'), unit='TRY'),
    'waste_to_revenue_pct': MetricContext(('waste', 'profitability'), '%'),
}


def scope_relation(anchor, candidate: KpiResult) -> str | None:
    if (candidate.company_id != anchor.company_id or candidate.tenant_id != anchor.tenant_id
            or candidate.period != anchor.period):
        return None
    if candidate.entity_type == anchor.entity_type and candidate.entity_id == anchor.entity_id:
        return 'same_entity'
    # Canonical calculator emits branch_product as branch-code:product-code.
    # Never admit sibling products, other branches, or arbitrary child scopes.
    policy = policy_for(anchor.metric)
    if (policy is not None and 'parent_branch' in policy.optional_scopes
            and anchor.entity_type == 'branch_product' and anchor.entity_id.count(':') == 1):
        branch, product = anchor.entity_id.split(':')
        if branch and product and candidate.entity_type == 'branch' and candidate.entity_id == branch:
            return 'parent_branch'
    return None


def snapshot_candidates(anchor, results: list[KpiResult]) -> list[KpiResult]:
    """Persist only the local entity and its permitted parent, not the whole company."""
    return sorted((k for k in results if scope_relation(anchor, k)),
                  key=lambda k: (k.entity_type, k.entity_id, k.metric, k.model_dump_json()))


@dataclass
class Selection:
    selected: list[tuple[KpiResult, str, str]] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    exclusions: list[dict[str, str]] = field(default_factory=list)
    policy: EvidencePolicy | None = None
    required_count: int | None = None
    present_required: int = 0
    omitted_count: int = 0


def select_context(anomaly, results: list[KpiResult], areas: list[str]) -> Selection:
    selection = Selection()
    spec = CATALOG.get(anomaly.metric, MetricContext(tuple(areas)))
    selection.policy = policy_for(anomaly.metric)
    required = selection.policy.required_metrics[1:] if selection.policy else ()
    selection.required_count = len(selection.policy.required_metrics) if selection.policy else None
    groups = defaultdict(list)
    for k in snapshot_candidates(anomaly, results):
        groups[(k.entity_type, k.entity_id, k.metric)].append(k)
    valid = {}
    for key, rows in sorted(groups.items()):
        k = rows[0]
        reason = None
        if len(rows) != 1:
            reason = 'duplicate_metric'
        elif k.status != 'ok' or k.value is None or not math.isfinite(k.value) or k.coverage <= 0:
            reason = 'invalid_or_unavailable'
        elif k.metric in CATALOG and CATALOG[k.metric].unit != k.unit:
            reason = 'unexpected_unit'
        elif k.snapshot_date:
            try:
                age = (date.fromisoformat(anomaly.period.end) - date.fromisoformat(k.snapshot_date)).days
                if age < 0 or age > get_settings().inventory_max_age_days:
                    reason = 'stale_or_future_snapshot'
            except ValueError:
                reason = 'invalid_snapshot_date'
        if reason:
            selection.exclusions.append(dict(metric=k.metric, entity_type=k.entity_type,
                                             entity_id=k.entity_id, reason=reason))
        else:
            valid[key] = k
    own_key = (anomaly.entity_type, anomaly.entity_id, anomaly.metric)
    own = valid.get(own_key)
    if own is None or own.value != anomaly.actual_value:
        selection.missing_required = [anomaly.metric, *required]
        return selection  # Context must never stand in for the actual anomaly.
    selection.selected.append((own, 'primary', 'same_entity'))
    selection.present_required = 1 if selection.policy else 0
    for metric in required:
        k = valid.get((anomaly.entity_type, anomaly.entity_id, metric))
        if k is None:
            selection.missing_required.append(metric)
        else:
            selection.selected.append((k, 'required_component', 'same_entity'))
            selection.present_required += 1
    chosen = {(k.entity_type, k.entity_id, k.metric) for k, _, _ in selection.selected}
    candidates = []
    own_sources = set(own.source_ids)
    domains = set(spec.areas) | set(areas)
    for key, k in valid.items():
        if key in chosen:
            continue
        relation = scope_relation(anomaly, k)
        shared = bool(own_sources & set(k.source_ids))
        related = bool(domains & set(CATALOG.get(k.metric, MetricContext(())).areas))
        if not (shared or related):
            continue
        reason = 'shared_source_records' if shared else 'related_financial_area'
        # Required components first; then local provenance, local domain, parent context.
        priority = (0 if relation == 'same_entity' else 2) + (0 if shared else 1)
        candidates.append((priority, -k.coverage, len(k.issues), key, k, reason, relation))
    candidates.sort(key=lambda row: row[:4])
    limit = selection.policy.max_signals if selection.policy else EXPLORATORY_MAX_SIGNALS
    slots = max(0, limit - len(selection.selected))
    selection.selected.extend((k, reason, relation) for _, _, _, _, k, reason, relation in candidates[:slots])
    selection.omitted_count = max(0, len(candidates) - slots)
    return selection
