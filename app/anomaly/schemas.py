from pydantic import BaseModel

from app.kpi.models import PeriodOut
from pydantic import ConfigDict, Field


class Anomaly(BaseModel):
    """Matches spec section 9. entity_ids is a list for forward-compatibility
    with future multi-entity anomalies; today it always holds exactly one id.
    """

    model_config = ConfigDict(allow_inf_nan=False)
    id: str
    company_id: str
    tenant_id: str
    run_id: str = ''
    kpi_snapshot: list[dict] = []
    threshold_snapshot: list[dict] = []
    entity_type: str
    entity_ids: list[str] = Field(min_length=1, max_length=1)
    metric: str
    actual_value: float
    threshold_value: float
    deviation: float
    severity: str
    department: str
    period: PeriodOut
    detected_at: str

    @property
    def entity_id(self) -> str:
        return self.entity_ids[0]

