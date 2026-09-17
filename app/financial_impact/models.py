from pydantic import BaseModel


class QuantifiedImpact(BaseModel):
    value: float
    unit: str
    formula: str
    metric: str = ''
    kind: str = 'observed_exposure'


class FinancialImpact(BaseModel):
    """Financial context and verified amounts; action selection belongs to generation."""

    anomaly_id: str
    metric: str
    problem_type: str
    financial_objective: str
    decision_type: str | None = None  # Legacy field; no action prescribed.
    financial_areas: list[str] = []
    information_gaps: list[str] = []
    assessment_status: str = 'review_required'
    department: str = "finance"
    support_departments: list[str]
    causal_chain: list[str]
    quantified_impact: QuantifiedImpact | None
    causation_caveat: str

