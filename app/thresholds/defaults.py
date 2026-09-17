"""Seed thresholds, used only to populate an empty database on first run.

These are illustrative starting values, not hardcoded engine behaviour —
once seeded, every value here lives in company_thresholds and can be
changed per company via PUT /companies/{company_id}/thresholds. The
threshold engine (app/thresholds/engine.py) never reads this module.
"""

from app.thresholds.schemas import ThresholdIn

_DEFAULTS: dict[str, list[ThresholdIn]] = {
    "COMP-001": [
        ThresholdIn(metric="gross_margin_pct", operator="less_than", warning_value=30, critical_value=20),
        ThresholdIn(metric="unit_cost_variance_pct", operator="greater_than", warning_value=15, critical_value=25),
        ThresholdIn(metric="days_inventory_outstanding", operator="greater_than", warning_value=45, critical_value=60),
        ThresholdIn(metric="branch_margin_gap_pct", operator="greater_than", warning_value=10, critical_value=18),
        ThresholdIn(
            metric="working_capital_in_inventory_pct", operator="greater_than", warning_value=50, critical_value=100
        ),
        ThresholdIn(metric="waste_to_revenue_pct", operator="greater_than", warning_value=5, critical_value=10),
    ],
    "COMP-002": [
        ThresholdIn(metric="gross_margin_pct", operator="less_than", warning_value=35, critical_value=25),
        ThresholdIn(metric="unit_cost_variance_pct", operator="greater_than", warning_value=10, critical_value=20),
        ThresholdIn(metric="days_inventory_outstanding", operator="greater_than", warning_value=30, critical_value=45),
        ThresholdIn(metric="branch_margin_gap_pct", operator="greater_than", warning_value=8, critical_value=15),
        ThresholdIn(
            metric="working_capital_in_inventory_pct", operator="greater_than", warning_value=40, critical_value=80
        ),
        ThresholdIn(metric="waste_to_revenue_pct", operator="greater_than", warning_value=3, critical_value=7),
    ],
}

# Used for any company_id not explicitly listed above (e.g. a real company
# imported through the actual Upload Center, identified by its own UUID) —
# every company gets a sensible starting point rather than silently getting
# no thresholds at all. Same shape as COMP-001's, adjustable per company via
# PUT /companies/{company_id}/thresholds once seeded.
_GENERIC_DEFAULTS: list[ThresholdIn] = [
    ThresholdIn(metric="gross_margin_pct", operator="less_than", warning_value=30, critical_value=20),
    ThresholdIn(metric="unit_cost_variance_pct", operator="greater_than", warning_value=15, critical_value=25),
    ThresholdIn(metric="days_inventory_outstanding", operator="greater_than", warning_value=45, critical_value=60),
    ThresholdIn(metric="branch_margin_gap_pct", operator="greater_than", warning_value=10, critical_value=18),
    ThresholdIn(
        metric="working_capital_in_inventory_pct", operator="greater_than", warning_value=50, critical_value=100
    ),
    ThresholdIn(metric="waste_to_revenue_pct", operator="greater_than", warning_value=5, critical_value=10),
]


def get_seed_thresholds(company_id: str) -> list[ThresholdIn]:
    return _DEFAULTS.get(company_id, _GENERIC_DEFAULTS)
