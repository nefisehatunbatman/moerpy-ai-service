"""Persisted RAG knowledge base: financial decisions + their embeddings.

approval_count / usage_count support the "approved decision learning" loop
(spec section 23): every time a manager approves a decision, if a close
enough match already exists in the KB, its counters are bumped instead of
inserting a duplicate.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeBaseEntry(Base):
    __tablename__ = "knowledge_base_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str | None] = mapped_column(String, nullable=True)  # null = cross-company, generic
    tenant_id: Mapped[str | None] = mapped_column(String,nullable=True,index=True)
    problem_type: Mapped[str] = mapped_column(String, nullable=False)
    decision_type: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str] = mapped_column(String, default="finance")
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    decision_text: Mapped[str] = mapped_column(String, nullable=False)
    financial_objective: Mapped[str] = mapped_column(String, nullable=False)
    expected_effect: Mapped[str] = mapped_column(String, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String, default="initial")  # "initial" | "approved_decision"
    approval_count: Mapped[int] = mapped_column(Integer, default=0)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    company_contexts: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    embedding_model: Mapped[str] = mapped_column(String,default='')
    embedding_dimensions: Mapped[int] = mapped_column(Integer,default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class LearningReceipt(Base):
    __tablename__='learning_receipts'
    decision_id: Mapped[str] = mapped_column(String,primary_key=True)
    entry_id: Mapped[str] = mapped_column(String,nullable=False)
