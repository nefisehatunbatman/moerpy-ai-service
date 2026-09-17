"""Deterministic severity scoring. No LLM involved.

Given how far a value sits inside the warning band, or past the critical
boundary, decide between low / medium / high / critical. The LLM never
sees a raw threshold breach without a severity already attached — it only
ever narrates a severity this module computed.
"""


def compute_severity(actual_value: float, warning_value: float, critical_value: float, status: str) -> str | None:
    if status == "ok":
        return None
    if status not in ("warning", "critical"):
        raise ValueError(f"Unexpected threshold status: {status}")

    band = abs(critical_value - warning_value) or 1e-9

    if status == "critical":
        overshoot_ratio = abs(actual_value - critical_value) / band
        return "critical" if overshoot_ratio >= 0.5 else "high"

    progress_ratio = abs(actual_value - warning_value) / band
    return "medium" if progress_ratio >= 0.5 else "low"


SEVERITY_LABELS_TR = {
    "low": "Düşük",
    "medium": "Orta",
    "high": "Yüksek",
    "critical": "Kritik",
}
