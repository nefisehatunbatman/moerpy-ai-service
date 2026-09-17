from pydantic import BaseModel, ConfigDict, model_validator
from typing import Literal


class ThresholdIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    metric: Literal['gross_margin_pct','unit_cost_variance_pct','days_inventory_outstanding','branch_margin_gap_pct','working_capital_in_inventory_pct','waste_to_revenue_pct']
    operator: Literal['less_than','greater_than','less_than_or_equal','greater_than_or_equal']
    warning_value: float
    critical_value: float
    department: str = "finance"
    active: bool = True

    @model_validator(mode='after')
    def validate_policy(self):
        low = self.metric == 'gross_margin_pct'
        if not low and min(self.warning_value, self.critical_value) < 0:
            raise ValueError('This metric requires nonnegative policy thresholds')
        if low != self.operator.startswith('less'):
            raise ValueError('Operator direction is incompatible with metric policy')
        if (low and self.critical_value >= self.warning_value) or (not low and self.critical_value <= self.warning_value):
            raise ValueError('Critical threshold must be beyond warning in the risk direction')
        if self.department != 'finance':
            raise ValueError('Financial policies must use finance department')
        return self


class ThresholdOut(ThresholdIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: str
    tenant_id: str

