from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CompanyThreshold(Base):
    """Persisted, company-specific threshold — never hardcoded in engine logic.

    operator is one of: greater_than, less_than, greater_than_or_equal,
    less_than_or_equal, absolute_deviation, percentage_deviation.
    """

    __tablename__ = "company_thresholds"
    __table_args__=(UniqueConstraint('tenant_id','company_id','metric',name='uq_policy_scope_metric'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String,nullable=False,index=True)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    operator: Mapped[str] = mapped_column(String, nullable=False)
    warning_value: Mapped[float] = mapped_column(Float, nullable=False)
    critical_value: Mapped[float] = mapped_column(Float, nullable=False)
    department: Mapped[str] = mapped_column(String, default="finance")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

