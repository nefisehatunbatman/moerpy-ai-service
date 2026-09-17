import pytest

from app.thresholds.models import CompanyThreshold
from app.thresholds.defaults import get_seed_thresholds
from app.thresholds.engine import evaluate
from app.thresholds.repository import ThresholdRepository
from app.thresholds.schemas import ThresholdIn


def test_seed_and_list(db_session):
    repo = ThresholdRepository(db_session)
    repo.seed_if_empty("COMP-001", get_seed_thresholds("COMP-001"))

    rows = repo.list_for_company("COMP-001")
    assert {r.metric for r in rows} == {
        "gross_margin_pct",
        "unit_cost_variance_pct",
        "days_inventory_outstanding",
        "branch_margin_gap_pct",
        "working_capital_in_inventory_pct",
        "waste_to_revenue_pct",
    }


def test_seed_is_idempotent(db_session):
    repo = ThresholdRepository(db_session)
    repo.seed_if_empty("COMP-001", get_seed_thresholds("COMP-001"))
    repo.seed_if_empty("COMP-001", get_seed_thresholds("COMP-001"))
    assert len(repo.list_for_company("COMP-001")) == 6


def test_upsert_overrides_existing(db_session):
    repo = ThresholdRepository(db_session)
    repo.seed_if_empty("COMP-001", get_seed_thresholds("COMP-001"))

    repo.upsert(
        "COMP-001",
        ThresholdIn(metric="gross_margin_pct", operator="less_than", warning_value=40, critical_value=30),
    )
    rows = repo.list_for_company("COMP-001")
    margin_row = next(r for r in rows if r.metric == "gross_margin_pct")
    assert margin_row.warning_value == 40
    assert len(rows) == 6  # no duplicate row created


def test_greater_than_operator_severity_bands(db_session):
    repo = ThresholdRepository(db_session)
    repo.seed_if_empty("COMP-001", get_seed_thresholds("COMP-001"))
    threshold = next(r for r in repo.list_for_company("COMP-001") if r.metric == "unit_cost_variance_pct")

    ok = evaluate(metric="unit_cost_variance_pct", entity_type="branch_product", entity_id="X", actual_value=5, threshold=threshold)
    warn = evaluate(metric="unit_cost_variance_pct", entity_type="branch_product", entity_id="X", actual_value=17, threshold=threshold)
    crit = evaluate(metric="unit_cost_variance_pct", entity_type="branch_product", entity_id="X", actual_value=30, threshold=threshold)

    assert ok.status == "ok"
    assert warn.status == "warning"
    assert crit.status == "critical"


def test_less_than_operator_severity_bands(db_session):
    repo = ThresholdRepository(db_session)
    repo.seed_if_empty("COMP-001", get_seed_thresholds("COMP-001"))
    threshold = next(r for r in repo.list_for_company("COMP-001") if r.metric == "gross_margin_pct")

    ok = evaluate(metric="gross_margin_pct", entity_type="company", entity_id="COMP-001", actual_value=35, threshold=threshold)
    warn = evaluate(metric="gross_margin_pct", entity_type="company", entity_id="COMP-001", actual_value=22, threshold=threshold)
    crit = evaluate(metric="gross_margin_pct", entity_type="company", entity_id="COMP-001", actual_value=15, threshold=threshold)

    assert ok.status == "ok"
    assert warn.status == "warning"
    assert crit.status == "critical"


def test_deviation_operator_without_baseline_does_not_false_positive(db_session):
    from app.thresholds.models import CompanyThreshold
    threshold=CompanyThreshold(company_id='COMP-003',metric='budget_variance_pct',operator='percentage_deviation',warning_value=10,critical_value=20)
    result = evaluate(
        metric="budget_variance_pct", entity_type="company", entity_id="COMP-003", actual_value=999, threshold=threshold
    )
    assert result.status == 'not_evaluated'

@pytest.mark.parametrize('actual_value', [0, 100, -100])
def test_percentage_deviation_zero_baseline_is_not_evaluated(actual_value):
    threshold = CompanyThreshold(
        company_id='COMP-003', metric='budget_variance_pct',
        operator='percentage_deviation', warning_value=10, critical_value=20,
    )
    result = evaluate(
        metric=threshold.metric, entity_type='company', entity_id='COMP-003',
        actual_value=actual_value, threshold=threshold, baseline_value=0,
    )
    assert result.status == 'not_evaluated'


@pytest.mark.parametrize('operator,baseline_value', [
    ('absolute_deviation', 0), ('percentage_deviation', 100),
])
@pytest.mark.parametrize('difference,expected', [(5, 'ok'), (15, 'warning'), (25, 'critical')])
def test_deviation_with_valid_baseline(operator, baseline_value, difference, expected):
    threshold = CompanyThreshold(
        company_id='COMP-003', metric='budget_variance_pct',
        operator=operator, warning_value=10, critical_value=20,
    )
    result = evaluate(
        metric=threshold.metric, entity_type='company', entity_id='COMP-003',
        actual_value=baseline_value + difference, threshold=threshold,
        baseline_value=baseline_value,
    )
    assert result.status == expected


def test_unsupported_policy_is_rejected_at_boundary():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ThresholdIn(metric='budget_variance_pct',operator='percentage_deviation',warning_value=10,critical_value=20)
