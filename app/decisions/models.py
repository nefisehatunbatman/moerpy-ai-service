from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DecisionRecord(Base):
    """Persisted Decision Card + everything needed to explain it later
    (evidence_snapshot, rag_snapshot) and to feed the approved-decision
    learning loop (problem_type, financial_objective, expected_effect).
    """

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String, default='')
    model_version: Mapped[str] = mapped_column(String, default='')
    prompt_version: Mapped[str] = mapped_column(String, default='v2')
    confidence_factors: Mapped[dict] = mapped_column(JSON, default=dict)
    learning_status: Mapped[str] = mapped_column(String, default='not_requested')
    learning_error: Mapped[str | None] = mapped_column(String, nullable=True)
    learning_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    anomaly_id: Mapped[str] = mapped_column(String, nullable=False)

    severity: Mapped[str] = mapped_column(String, nullable=False)
    decision_type: Mapped[str] = mapped_column(String, nullable=False)
    problem_type: Mapped[str] = mapped_column(String, nullable=False)
    financial_objective: Mapped[str] = mapped_column(String, nullable=False)

    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    problem_signal: Mapped[str] = mapped_column(String, nullable=False)
    recommended_decision: Mapped[str] = mapped_column(String, nullable=False)
    reasoning: Mapped[list] = mapped_column(JSON, default=list)
    expected_impact: Mapped[list] = mapped_column(JSON, default=list)

    department: Mapped[str] = mapped_column(String, default="finance")
    support_departments: Mapped[list] = mapped_column(JSON, default=list)
    signals: Mapped[list] = mapped_column(JSON, default=list)

    confidence_score: Mapped[int] = mapped_column(default=0)
    confidence_band: Mapped[str] = mapped_column(String, default="low")
    rag_top_similarity: Mapped[float] = mapped_column(Float, default=0.0)
    rag_matched_decision_ids: Mapped[list] = mapped_column(JSON, default=list)

    evidence_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    rag_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    generator_name: Mapped[str] = mapped_column(String, default="")

    status: Mapped[str] = mapped_column(String, default="PROPOSED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class DecisionLifecycleEvent(Base):
    """Audit trail: every state transition a decision goes through."""

    __tablename__ = "decision_lifecycle_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String, nullable=True)
    to_status: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

