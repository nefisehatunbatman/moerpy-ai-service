from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from app.data.models import Period


class PeriodOut(BaseModel):
    start: str
    end: str

    @classmethod
    def from_period(cls, period: Period) -> "PeriodOut":
        return cls(start=period.start.isoformat(), end=period.end.isoformat())


class KpiResult(BaseModel):
    """One deterministically-computed financial KPI value. Matches spec section 7."""
    model_config = ConfigDict(allow_inf_nan=False)

    company_id: str
    entity_type: str  # "company" | "branch" | "branch_product"
    entity_id: str
    metric: str
    value: float | None
    unit: str  # "TRY" | "%" | "days" | "ratio"
    period: PeriodOut
    source: str  # which fact tables fed this value
    formula: str  # human-readable formula, so the calculation is explainable
    calculated_at: str
    tenant_id: str
    status: str = 'ok'
    issues: list[str] = []
    coverage: float = Field(default=1.0, ge=0, le=1)
    source_ids: list[str] = []
    import_batch_ids: list[str] = []
    source_count: int = 0
    source_digest: str = ''
    snapshot_date: str | None = None

    @classmethod
    def now(cls, **kwargs) -> "KpiResult":
        return cls(calculated_at=datetime.now(timezone.utc).isoformat(), **kwargs)

