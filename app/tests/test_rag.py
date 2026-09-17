from datetime import date

from app.anomaly.detector import detect_anomalies
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


def _build_evidence_for(metric, company_id, db_session):
    repo = ThresholdRepository(db_session)
    repo.seed_if_empty(company_id, get_seed_thresholds(company_id))
    thresholds = repo.list_for_company(company_id)
    kpis = compute_kpis(FakeERPDataProvider(), company_id, FEB)
    anomalies = detect_anomalies(company_id, FEB, kpis, thresholds)
    anomaly = next(a for a in anomalies if a.metric == metric)
    impact = analyze(anomaly, kpis)
    return build_evidence(anomaly, impact, kpis, thresholds)


def test_seeding_loads_six_initial_decisions(db_session):
    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()
    entries = kb.list_all()
    assert len(entries) == 6
    assert all(e.source == "initial" for e in entries)


def test_seeding_is_idempotent(db_session):
    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()
    kb.seed_if_empty()
    assert len(kb.list_all()) == 6


def test_retrieval_finds_matching_decision_type_for_cash_flow_anomaly(db_session):
    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()
    evidence = _build_evidence_for("working_capital_in_inventory_pct", "COMP-001", db_session)

    results = retrieve(kb, evidence, top_k=3)
    assert len(results) > 0
    top = results[0]
    assert top.decision_type == "CASH_FLOW"
    assert top.problem_type == "cash_locked_in_inventory"


def test_retrieval_finds_matching_decision_type_for_cost_optimization_anomaly(db_session):
    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()
    evidence = _build_evidence_for("unit_cost_variance_pct", "COMP-001", db_session)

    results = retrieve(kb, evidence, top_k=3)
    assert results[0].decision_type == "COST_OPTIMIZATION"


def test_duplicate_detection_matches_identical_decision(db_session):
    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()
    existing = kb.get("KB-0003")

    duplicate = kb.find_duplicate("unit_cost_overrun", "COST_OPTIMIZATION", existing.decision_text, "COMP-001")
    assert duplicate is not None
    assert duplicate[0].id == "KB-0003"


def test_approved_decision_reuses_near_duplicate_instead_of_inserting(db_session):
    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()
    existing = kb.get("KB-0003")

    learned = kb.record_approved_decision(
        company_id="COMP-001",
        problem_type="unit_cost_overrun",
        decision_type="COST_OPTIMIZATION",
        department="finance",
        signals=["unit_cost_variance_pct"],
        conditions={},
        decision_text=existing.decision_text,
        financial_objective="protect_margin",
        expected_effect="Birim maliyet sapmasının azalması beklenmektedir.",
    )

    assert len(kb.list_all()) == 7  # first approval creates a private company entry
    refreshed = kb.get("KB-0003")
    assert refreshed.approval_count == 0
    assert refreshed.company_contexts == []
    assert learned.company_id == "COMP-001" and learned.approval_count == 1


def test_genuinely_new_decision_gets_inserted(db_session):
    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()

    kb.record_approved_decision(
        company_id="COMP-005",
        problem_type="entirely_new_problem_type_never_seen_before",
        decision_type="CAPEX",
        department="finance",
        signals=["some_metric"],
        conditions={},
        decision_text="Tamamen farklı ve daha önce hiç görülmemiş bir CAPEX kararı metni burada yer almaktadır.",
        financial_objective="optimize_capex",
        expected_effect="Sermaye harcamalarının verimliliğinin artması beklenmektedir.",
    )
    assert len(kb.list_all()) == 7
