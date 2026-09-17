"""Versioned evidence requirements, independent of financial action selection.

Policies describe metric identities and permitted scopes, never magic counts.
Changes are reviewed in code; snapshots retain the exact policy used.
"""
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidencePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    id: str
    version: str
    metric: str
    required_metrics: tuple[str, ...]
    required_scope: Literal['same_entity'] = 'same_entity'
    optional_scopes: tuple[Literal['same_entity', 'parent_branch'], ...] = ('same_entity',)
    max_signals: int = Field(default=8, ge=1, le=32)

    @model_validator(mode='after')
    def valid_requirements(self):
        if not self.id.strip() or not self.version.strip():
            raise ValueError('Policy identity and version are required')
        if not self.required_metrics or self.required_metrics[0] != self.metric:
            raise ValueError('Primary metric must be the first requirement')
        if len(set(self.required_metrics)) != len(self.required_metrics):
            raise ValueError('Duplicate evidence requirement')
        if len(self.required_metrics) > self.max_signals:
            raise ValueError('Signal budget cannot exclude required metrics')
        return self


_REQUIREMENTS = {
    'gross_margin_pct': ('revenue', 'cogs'),
    'branch_margin_gap_pct': ('branch_margin_gap_try',),
    'unit_cost_variance_pct': ('unit_cost_variance_try',),
    'days_inventory_outstanding': ('inventory_value', 'cogs'),
    'working_capital_in_inventory_pct': ('inventory_value', 'revenue'),
    'waste_to_revenue_pct': ('waste_value_try', 'revenue'),
}
POLICIES = {metric: EvidencePolicy(id='financial-evidence/' + metric, version='1', metric=metric,
    required_metrics=(metric, *required),
    optional_scopes=('same_entity', 'parent_branch') if metric == 'unit_cost_variance_pct' else ('same_entity',))
    for metric, required in _REQUIREMENTS.items()}

# Unknown metrics still get bounded exploratory context, but no completeness policy.
EXPLORATORY_MAX_SIGNALS = 8
POLICY_REVISION = hashlib.sha256(json.dumps(
    {key: policy.model_dump(mode='json') for key, policy in sorted(POLICIES.items())},
    sort_keys=True).encode()).hexdigest()[:16]


def policy_for(metric: str) -> EvidencePolicy | None:
    return POLICIES.get(metric)


def completeness(evidence) -> float | None:
    """Use the saved policy and distinct scoped signals, not legacy counters."""
    policy = evidence.evidence_policy
    if policy is None or not evidence.signals or evidence.signals[0].metric != policy.metric:
        return None if policy is None else 0.0
    present = {s.metric for s in evidence.signals
               if s.scope_relation == policy.required_scope
               and s.entity_type == evidence.entity_type and s.entity_id == evidence.entity_id
               and s.coverage > 0}
    return len(present & set(policy.required_metrics)) / len(policy.required_metrics)
