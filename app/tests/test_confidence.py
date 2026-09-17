from datetime import date

from app.anomaly.detector import detect_anomalies
from app.confidence.engine import compute_confidence
from app.data.models import Period
from app.data.providers.fake_provider import FakeERPDataProvider
from app.evidence.builder import build_evidence
from app.financial_impact.analyzer import analyze
from app.kpi.engine import compute_kpis
from app.rag.embeddings import LocalHashEmbedding
from app.rag.knowledge_base import KnowledgeBaseRepository
from app.rag.retriever import retrieve
from app.thresholds.defaults import get_seed_thresholds
from app.thresholds.repository import ThresholdRepository

FEB = Period(start=date(2026, 2, 1), end=date(2026, 2, 28))


def _pipeline(metric, company_id, db_session):
    repo = ThresholdRepository(db_session)
    repo.seed_if_empty(company_id, get_seed_thresholds(company_id))
    thresholds = repo.list_for_company(company_id)
    kpis = compute_kpis(FakeERPDataProvider(), company_id, FEB)
    anomalies = detect_anomalies(company_id, FEB, kpis, thresholds)
    anomaly = next(a for a in anomalies if a.metric == metric)
    impact = analyze(anomaly, kpis)
    evidence = build_evidence(anomaly, impact, kpis, thresholds)
    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()
    retrieved = retrieve(kb, evidence, top_k=3)
    return evidence, anomaly.severity, retrieved


def test_critical_anomaly_scores_higher_than_low_severity(db_session):
    evidence_critical, severity_critical, retrieved_critical = _pipeline(
        "working_capital_in_inventory_pct", "COMP-001", db_session
    )
    evidence_low, severity_low, retrieved_low = _pipeline("waste_to_revenue_pct", "COMP-001", db_session)

    reference_day = date(2026, 3, 1)  # inside recency grace window, isolates the severity effect
    critical_score = compute_confidence(evidence_critical, severity_critical, retrieved_critical, today=reference_day)
    low_score = compute_confidence(evidence_low, severity_low, retrieved_low, today=reference_day)

    assert severity_critical == "critical"
    assert severity_low == "low"
    assert critical_score.score > low_score.score


def test_score_is_bounded_0_to_100(db_session):
    evidence, severity, retrieved = _pipeline("working_capital_in_inventory_pct", "COMP-001", db_session)
    result = compute_confidence(evidence, severity, retrieved, today=date(2026, 3, 1))
    assert 0 <= result.score <= 100


def test_band_thresholds():
    from app.confidence.engine import _band

    assert _band(39) == "low"
    assert _band(40) == "medium"
    assert _band(69) == "medium"
    assert _band(70) == "high"


def test_stale_period_reduces_recency_factor(db_session):
    evidence, severity, retrieved = _pipeline("working_capital_in_inventory_pct", "COMP-001", db_session)

    fresh = compute_confidence(evidence, severity, retrieved, today=date(2026, 3, 5))
    stale = compute_confidence(evidence, severity, retrieved, today=date(2027, 3, 5))

    assert fresh.factors.data_recency == 1.0
    assert stale.factors.data_recency < fresh.factors.data_recency
    assert stale.score < fresh.score


def test_no_retrieved_decisions_yields_zero_rag_similarity(db_session):
    evidence, severity, _ = _pipeline("working_capital_in_inventory_pct", "COMP-001", db_session)
    result = compute_confidence(evidence, severity, [], today=date(2026, 3, 1))
    assert result.factors.rag_similarity == 0.0
