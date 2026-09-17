from pydantic import BaseModel

from app.financial_impact.models import QuantifiedImpact
from app.kpi.models import PeriodOut
from app.evidence.policies import EvidencePolicy


class Signal(BaseModel):
    metric: str
    label: str
    value: float
    unit: str
    formula: str
    entity_id: str = ''
    entity_type: str = ''
    selection_reason: str = 'legacy'
    scope_relation: str = 'same_entity'
    source_ids: list[str] = []
    source_count: int = 0
    source_digest: str = ''
    coverage: float = 1.0
    issues: list[str] = []
    snapshot_date: str | None = None


class ThresholdSummary(BaseModel):
    metric: str
    operator: str
    warning_value: float
    critical_value: float


class EvidencePackage(BaseModel):
    """The ONLY thing the LLM ever sees for a given anomaly. Every number in
    it was computed by the KPI/anomaly/financial-impact engines — nothing
    here is written by the LLM, and the LLM is instructed to use no other
    numbers than these (see app/llm/prompts.py).
    """

    anomaly_id: str
    company_id: str
    tenant_id: str
    entity_id: str = ''
    entity_type: str = ''
    run_id: str = ''
    import_batch_ids: list[str] = []
    quality_issues: list[str] = []
    language: str = 'tr'
    problem_type: str
    financial_objective: str
    decision_type: str | None = None
    financial_areas: list[str] = []
    information_gaps: list[str] = []
    assessment_status: str = 'context_available'
    context_selection_version: str = 'legacy'
    evidence_policy: EvidencePolicy | None = None
    completeness_status: str = 'unknown'
    context_required_count: int | None = None
    context_present_required: int = 0
    context_omitted_count: int = 0
    context_exclusions: list[dict[str, str]] = []
    confidence_reasons: list[str] = []
    department: str
    support_departments: list[str]
    severity: str
    period: PeriodOut
    signals: list[Signal]
    thresholds: list[ThresholdSummary]
    quantified_impact: QuantifiedImpact | None
    causal_chain: list[str]
    causation_caveat: str

