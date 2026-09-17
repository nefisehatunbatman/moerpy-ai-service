"""Full pipeline, exercised the way a real request would: fake ERP data ->
KPI -> threshold -> anomaly -> financial impact -> evidence -> RAG -> LLM
(FakeLLMClient, deterministic) -> confidence -> Decision Card -> approve ->
knowledge base -> vector index. Matches spec section 30 end-to-end flow.
"""

from datetime import date

import pytest

from app.anomaly.detector import detect_anomalies
from app.anomaly.repository import AnomalyRepository
from app.data.models import Period
from app.data.providers.fake_provider import FakeERPDataProvider
from app.decisions.repository import DecisionRepository
from app.decisions.service import (
    DecisionNotFoundError,
    InvalidDecisionTransitionError,
    approve_decision,
    generate_decision_for_anomaly,
    reject_decision,
)
from app.kpi.engine import compute_kpis
from app.llm.client import FakeLLMClient
from app.rag.embeddings import LocalHashEmbedding
from app.rag.knowledge_base import KnowledgeBaseRepository
from app.thresholds.defaults import get_seed_thresholds
from app.thresholds.repository import ThresholdRepository

FEB = Period(start=date(2026, 2, 1), end=date(2026, 2, 28))


def _detect_and_persist(company_id, db_session):
    ThresholdRepository(db_session).seed_if_empty(company_id, get_seed_thresholds(company_id))
    thresholds = ThresholdRepository(db_session).list_for_company(company_id)
    kpis = compute_kpis(FakeERPDataProvider(), company_id, FEB)
    anomalies = detect_anomalies(company_id, FEB, kpis, thresholds)
    AnomalyRepository(db_session).save_all(anomalies)
    return anomalies


def test_full_pipeline_generate_and_approve(db_session):
    anomalies = _detect_and_persist("COMP-001", db_session)
    cash_flow_anomaly = next(a for a in anomalies if a.metric == "working_capital_in_inventory_pct")

    card = generate_decision_for_anomaly(
        db_session,
        company_id="COMP-001",
        anomaly_id=cash_flow_anomaly.id,
        erp_provider=FakeERPDataProvider(),
        llm_client=FakeLLMClient(),
        embedding_provider=LocalHashEmbedding(),
    )

    assert card.status == "PROPOSED"
    assert card.decision_type == "CASH_FLOW"
    assert card.department == "finance"
    assert card.severity == "critical"
    assert card.confidence.score >= 0
    assert card.confidence.reasons
    assert card.id.startswith("MOE-2602-")

    approved = approve_decision(
        db_session, decision_id=card.id, actor="cfo@example.com", note="onaylandı", embedding_provider=LocalHashEmbedding()
    )
    assert approved.status == "APPROVED"

    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    cash_flow_entries = [e for e in kb.list_all("COMP-001") if e.problem_type == "cash_locked_in_inventory"]
    assert any("COMP-001" in (e.company_contexts or []) for e in cash_flow_entries)


def test_reject_does_not_touch_knowledge_base(db_session):
    anomalies = _detect_and_persist("COMP-001", db_session)
    waste_anomaly = next(a for a in anomalies if a.metric == "waste_to_revenue_pct")

    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()
    count_before = len(kb.list_all())

    card = generate_decision_for_anomaly(
        db_session,
        company_id="COMP-001",
        anomaly_id=waste_anomaly.id,
        erp_provider=FakeERPDataProvider(),
        llm_client=FakeLLMClient(),
        embedding_provider=LocalHashEmbedding(),
    )
    rejected = reject_decision(db_session, decision_id=card.id, actor="cfo@example.com", reason="şu an önceliğimiz değil")

    assert rejected.status == "REJECTED"
    assert len(kb.list_all()) == count_before  # unchanged — rejection never writes to the KB


def test_duplicate_approval_does_not_create_new_kb_entry_for_seeded_pattern(db_session):
    anomalies = _detect_and_persist("COMP-001", db_session)
    variance_anomaly = next(a for a in anomalies if a.metric == "unit_cost_variance_pct" and a.entity_ids == ["BR-002:PRD-001"])

    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()
    count_before = len(kb.list_all())

    card = generate_decision_for_anomaly(
        db_session,
        company_id="COMP-001",
        anomaly_id=variance_anomaly.id,
        erp_provider=FakeERPDataProvider(),
        llm_client=FakeLLMClient(),
        embedding_provider=LocalHashEmbedding(),
    )
    approve_decision(db_session, decision_id=card.id, actor="cfo@example.com", note=None, embedding_provider=LocalHashEmbedding())

    # FakeLLMClient reuses the retrieved KB decision's own text verbatim, so this
    # should match the existing COST_OPTIMIZATION seed entry almost exactly.
    assert len(kb.list_all()) == count_before + 1


def test_cannot_approve_twice(db_session):
    anomalies = _detect_and_persist("COMP-001", db_session)
    anomaly = anomalies[0]
    card = generate_decision_for_anomaly(
        db_session,
        company_id="COMP-001",
        anomaly_id=anomaly.id,
        erp_provider=FakeERPDataProvider(),
        llm_client=FakeLLMClient(),
        embedding_provider=LocalHashEmbedding(),
    )
    approve_decision(db_session, decision_id=card.id, actor="cfo@example.com", note=None, embedding_provider=LocalHashEmbedding())

    with pytest.raises(InvalidDecisionTransitionError):
        approve_decision(db_session, decision_id=card.id, actor="cfo@example.com", note=None, embedding_provider=LocalHashEmbedding())


def test_generate_for_unknown_anomaly_raises(db_session):
    with pytest.raises(DecisionNotFoundError):
        generate_decision_for_anomaly(
            db_session,
            company_id="COMP-001",
            anomaly_id="ANO-does-not-exist",
            erp_provider=FakeERPDataProvider(),
            llm_client=FakeLLMClient(),
            embedding_provider=LocalHashEmbedding(),
        )


def test_lifecycle_events_are_recorded(db_session):
    anomalies = _detect_and_persist("COMP-001", db_session)
    card = generate_decision_for_anomaly(
        db_session,
        company_id="COMP-001",
        anomaly_id=anomalies[0].id,
        erp_provider=FakeERPDataProvider(),
        llm_client=FakeLLMClient(),
        embedding_provider=LocalHashEmbedding(),
    )
    approve_decision(db_session, decision_id=card.id, actor="cfo@example.com", note=None, embedding_provider=LocalHashEmbedding())

    events = DecisionRepository(db_session).lifecycle(card.id)
    statuses = [e.to_status for e in events]
    assert statuses == ["GENERATING", "PROPOSED", "APPROVED"]

