"""Confidence Engine — entirely deterministic, never touched by the LLM.

Combines seven 0-1 factors into a single 0-100 score with a fixed weighted
formula (spec section 19's starting point). Every factor is computed from
data the rest of the pipeline already produced — nothing here is a guess.
"""

from datetime import date
from app.core.dates import reporting_today

from app.confidence.models import ConfidenceFactors, ConfidenceScore
from app.evidence.models import EvidencePackage
from app.rag.retriever import RetrievedDecision
from app.evidence.policies import completeness

_WEIGHTS = {
    "data_quality": 0.20,
    "data_completeness": 0.15,
    "anomaly_strength": 0.20,
    "rag_similarity": 0.20,
    "historical_support": 0.10,
    "evidence_coverage": 0.10,
    "data_recency": 0.05,
}

_SEVERITY_STRENGTH = {"low": 0.30, "medium": 0.55, "high": 0.80, "critical": 1.00}

_RECENCY_GRACE_DAYS = 35  # inside the typical monthly reporting cycle -> full recency score
_RECENCY_DECAY_DAYS = 365


def _data_quality(evidence: EvidencePackage) -> float:
    if not evidence.signals: return 0.0
    return sum(s.coverage * (0.5 if s.issues else 1.0) for s in evidence.signals)/len(evidence.signals)


def _data_completeness(evidence: EvidencePackage) -> float:
    # An absent policy means requirements are unknown, never that the primary
    # signal is complete. Keep the numeric factor conservative for scoring;
    # the evidence package exposes completeness_status='unknown'.
    value = completeness(evidence)
    return value if value is not None else 0.0


def _anomaly_strength(severity: str) -> float:
    return _SEVERITY_STRENGTH.get(severity, 0.3)


def _rag_similarity(retrieved: list[RetrievedDecision]) -> float:
    return max(0.0, min(1.0, retrieved[0].similarity)) if retrieved else 0.0


def _historical_support(evidence: EvidencePackage, retrieved: list[RetrievedDecision]) -> float:
    if not retrieved:
        return 0.0
    # Initial templates are not measured business outcomes.
    # Approval is not a measured outcome. No outcome measurement contract yet.
    return 0.0


def _evidence_coverage(evidence: EvidencePackage) -> float:
    value = completeness(evidence)
    if value is None:
        return 0.0
    if evidence.quantified_impact is not None and value >= 1.0:
        return 1.0
    return value


def _data_recency(period_end: date, today: date) -> float:
    days_old = (today - period_end).days
    if days_old <= _RECENCY_GRACE_DAYS:
        return 1.0
    decayed = 1.0 - (days_old - _RECENCY_GRACE_DAYS) / _RECENCY_DECAY_DAYS
    return max(0.2, decayed)


def _band(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def confidence_reasons(evidence: EvidencePackage, factors: ConfidenceFactors) -> list[str]:
    """Explain evidence sufficiency; this is not a success probability."""
    reasons = []
    if evidence.completeness_status == 'unknown':
        reasons.append('evidence_policy_missing')
    elif factors.data_completeness < 1:
        reasons.append('required_context_incomplete')
    if factors.data_quality < 0.8:
        reasons.append('source_quality_or_coverage_limited')
    if factors.rag_similarity < 0.35:
        reasons.append('no_strong_similar_approved_decision')
    if factors.historical_support == 0:
        reasons.append('historical_outcome_support_missing')
    if factors.data_recency < 0.8:
        reasons.append('period_is_not_recent')
    return reasons or ['verified_context_is_complete_for_policy']


def compute_confidence(
    evidence: EvidencePackage,
    severity: str,
    retrieved: list[RetrievedDecision],
    today: date | None = None,
) -> ConfidenceScore:
    today = today or reporting_today()
    period_end = min([date.fromisoformat(evidence.period.end)]+[date.fromisoformat(s.snapshot_date) for s in evidence.signals if s.snapshot_date])

    factors = ConfidenceFactors(
        data_quality=_data_quality(evidence),
        data_completeness=_data_completeness(evidence),
        anomaly_strength=_anomaly_strength(severity),
        rag_similarity=_rag_similarity(retrieved),
        historical_support=_historical_support(evidence, retrieved),
        evidence_coverage=_evidence_coverage(evidence),
        data_recency=_data_recency(period_end, today),
    )

    weighted_sum = sum(getattr(factors, key) * weight for key, weight in _WEIGHTS.items())
    score = round(weighted_sum * 100)
    score = max(0, min(100, score))
    if evidence.assessment_status == 'review_required':
        score = min(score, 39)

    return ConfidenceScore(score=score, band=_band(score), factors=factors)
