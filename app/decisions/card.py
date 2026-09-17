"""Decision Card — the single API response model that feeds both the card
view and the detail view (spec section 20). This is the only shape the
existing frontend/backend would ever need to consume.
"""

from pydantic import BaseModel

from app.anomaly.severity import SEVERITY_LABELS_TR


class ExpectedImpactOut(BaseModel):
    metric: str
    label: str
    direction: str
    type: str
    value: float | None = None
    unit: str | None = None


class SignalOut(BaseModel):
    metric: str
    label: str
    value: float
    unit: str
    entity_id: str = ''
    entity_type: str = ''
    selection_reason: str = 'legacy'
    scope_relation: str = 'same_entity'


class ConfidenceOut(BaseModel):
    score: int
    band: str
    interpretation: str = 'heuristic_evidence_sufficiency_not_probability'
    factors: dict[str,float] = {}
    reasons: list[str] = []


class RagOut(BaseModel):
    top_similarity: float
    matched_decision_ids: list[str]


class DecisionCard(BaseModel):
    id: str
    severity: str
    severity_label_tr: str
    decision_type: str
    title: str
    summary: str
    department: str
    support_departments: list[str]
    problem_signal: str
    signals: list[SignalOut]
    recommended_decision: str
    reasoning: list[str]
    expected_impact: list[ExpectedImpactOut]
    confidence: ConfidenceOut
    rag: RagOut
    status: str
    company_id: str = ''
    tenant_id: str = ''
    entity_id: str = ''
    entity_type: str = ''
    period: dict = {}
    run_id: str = ''
    generator: str = ''
    model_version: str = ''
    prompt_version: str = ''
    learning_status: str = 'not_requested'
    observed_impact: dict | None = None
    language: str = 'tr'
    assessment_status: str = 'review_required'
    financial_areas: list[str] = []
    information_gaps: list[str] = []
    decision_readiness: str = 'legacy_unverified'
    action_id: str | None = None
    action_policy_source: str = 'unknown'
    blockers: list[str] = []
    risks: list[str] = []
    do_not_apply_when: list[str] = []
    success_metric: dict = {}
    impact_assessment: dict = {}
    traceability: dict = {}


def severity_label(severity: str) -> str:
    return SEVERITY_LABELS_TR.get(severity, severity)
