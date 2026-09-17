from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnomalyRecord(Base):
    """Persisted anomaly — written once by the anomaly engine, then referenced
    by id from generate-decision / evidence / API responses. Never written to
    by the LLM.
    """

    __tablename__ = "anomalies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String, default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    kpi_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    threshold_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    actual_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    deviation: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)  # low | medium | high | critical
    department: Mapped[str] = mapped_column(String, default="finance")
    period_start: Mapped[str] = mapped_column(String, nullable=False)
    period_end: Mapped[str] = mapped_column(String, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

