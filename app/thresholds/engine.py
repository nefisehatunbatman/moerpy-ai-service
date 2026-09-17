"""Deterministic threshold comparison. No LLM involved.

Given an actual KPI value and a persisted CompanyThreshold row, decides
whether the metric is ok / warning / critical, and by how much.
"""

from dataclasses import dataclass

from app.thresholds.models import CompanyThreshold

VALID_OPERATORS = {
    "greater_than",
    "less_than",
    "greater_than_or_equal",
    "less_than_or_equal",
    "absolute_deviation",
    "percentage_deviation",
}


@dataclass(frozen=True)
class ThresholdEvaluation:
    metric: str
    entity_type: str
    entity_id: str
    actual_value: float
    threshold_value: float  # the boundary that was crossed (warning or critical)
    deviation: float
    status: str  # "ok" | "warning" | "critical" | "not_evaluated"
    operator: str
    department: str


def evaluate(
    *,
    metric: str,
    entity_type: str,
    entity_id: str,
    actual_value: float,
    threshold: CompanyThreshold,
    baseline_value: float | None = None,
) -> ThresholdEvaluation:
    if threshold.operator not in VALID_OPERATORS:
        raise ValueError(f"Unknown threshold operator: {threshold.operator}")

    status, threshold_value = _compare(threshold.operator, actual_value, threshold, baseline_value)
    deviation = round(actual_value - threshold_value, 4) if threshold_value is not None else 0.0

    return ThresholdEvaluation(
        metric=metric,
        entity_type=entity_type,
        entity_id=entity_id,
        actual_value=actual_value,
        threshold_value=threshold_value if threshold_value is not None else 0.0,
        deviation=deviation,
        status=status,
        operator=threshold.operator,
        department=threshold.department,
    )


def _compare(
    operator: str,
    actual_value: float,
    threshold: CompanyThreshold,
    baseline_value: float | None,
) -> tuple[str, float | None]:
    warning = threshold.warning_value
    critical = threshold.critical_value

    if operator == "greater_than":
        if actual_value > critical:
            return "critical", critical
        if actual_value > warning:
            return "warning", warning
        return "ok", warning

    if operator == "greater_than_or_equal":
        if actual_value >= critical:
            return "critical", critical
        if actual_value >= warning:
            return "warning", warning
        return "ok", warning

    if operator == "less_than":
        if actual_value < critical:
            return "critical", critical
        if actual_value < warning:
            return "warning", warning
        return "ok", warning

    if operator == "less_than_or_equal":
        if actual_value <= critical:
            return "critical", critical
        if actual_value <= warning:
            return "warning", warning
        return "ok", warning

    if operator in ("absolute_deviation", "percentage_deviation"):
        if baseline_value is None:
            # No verified baseline supplied for this evaluation — cannot judge a
            # deviation without one, so we do not guess. Caller should treat this
            # metric as not evaluated rather than silently "ok".
            return "not_evaluated", None
        if operator == "percentage_deviation" and baseline_value == 0:
            # A percentage relative to zero is undefined, including 0 / 0.
            return "not_evaluated", None
        diff = actual_value - baseline_value
        deviation = abs(diff) if operator == "absolute_deviation" else abs(diff) / abs(baseline_value) * 100
        if deviation > critical:
            return "critical", critical
        if deviation > warning:
            return "warning", warning
        return "ok", warning

    raise ValueError(f"Unhandled operator: {operator}")  # pragma: no cover
