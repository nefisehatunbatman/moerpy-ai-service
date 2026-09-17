"""Every expected value here was hand-computed from the fixture dataset
(app/data/fixtures/*.json) before this test was written — see the fixture
files for the raw numbers. This is the ground truth the KPI engine is
checked against.
"""

from datetime import date

import pytest

from app.data.models import Period
from app.data.providers.fake_provider import FakeERPDataProvider
from app.kpi.engine import compute_kpis

FEB = Period(start=date(2026, 2, 1), end=date(2026, 2, 28))


@pytest.fixture
def provider():
    return FakeERPDataProvider()


def _get(results, metric, entity_id):
    matches = [r for r in results if r.metric == metric and r.entity_id == entity_id]
    assert len(matches) == 1, f"expected exactly one {metric}/{entity_id}, got {len(matches)}"
    return matches[0]


def test_company_revenue_and_margin(provider):
    results = compute_kpis(provider, "COMP-001", FEB)

    company_revenue = _get(results, "revenue", "COMP-001")
    assert company_revenue.value == 1_025_000

    company_margin = _get(results, "gross_margin_pct", "COMP-001")
    assert company_margin.value == pytest.approx(28.29, abs=0.01)


def test_branch_margin_gap_between_br001_and_br002(provider):
    results = compute_kpis(provider, "COMP-001", FEB)

    br001_margin = _get(results, "gross_margin_pct", "BR-001")
    br002_margin = _get(results, "gross_margin_pct", "BR-002")
    assert br001_margin.value == pytest.approx(32.57, abs=0.01)
    assert br002_margin.value == pytest.approx(19.08, abs=0.01)

    gap = _get(results, "branch_margin_gap_pct", "COMP-001")
    assert gap.value == pytest.approx(13.49, abs=0.02)


def test_unit_cost_variance_flags_br002_overrun(provider):
    results = compute_kpis(provider, "COMP-001", FEB)

    br002_kulaklik = _get(results, "unit_cost_variance_pct", "BR-002:PRD-001")
    assert br002_kulaklik.value == pytest.approx(22.86, abs=0.01)

    br001_kulaklik = _get(results, "unit_cost_variance_pct", "BR-001:PRD-001")
    assert br001_kulaklik.value == 0.0


def test_days_inventory_outstanding_is_much_higher_for_br002(provider):
    results = compute_kpis(provider, "COMP-001", FEB)

    br001_dio = _get(results, "days_inventory_outstanding", "BR-001")
    br002_dio = _get(results, "days_inventory_outstanding", "BR-002")
    assert br001_dio.value < 10
    assert br002_dio.value == pytest.approx(52.4, abs=0.2)


def test_working_capital_in_inventory_flags_br002(provider):
    results = compute_kpis(provider, "COMP-001", FEB)

    br002_wc = _get(results, "working_capital_in_inventory_pct", "BR-002")
    assert br002_wc.value == pytest.approx(151.4, abs=0.2)


def test_waste_to_revenue_flags_br002(provider):
    results = compute_kpis(provider, "COMP-001", FEB)

    # Verified event cost from the fixture: 22000 / 325000 * 100 = 6.77%.
    br002_waste = _get(results, "waste_to_revenue_pct", "BR-002")
    assert br002_waste.value == pytest.approx(6.77, abs=0.02)


def test_comp002_is_clean(provider):
    results = compute_kpis(provider, "COMP-002", FEB)

    company_margin = _get(results, "gross_margin_pct", "COMP-002")
    assert company_margin.value == pytest.approx(42.8, abs=0.1)

    for r in results:
        if r.metric == "unit_cost_variance_pct":
            assert abs(r.value) < 5
        if r.metric == "days_inventory_outstanding":
            assert r.value < 10
        if r.metric == "working_capital_in_inventory_pct":
            assert r.value < 20

    assert not any(r.metric == "branch_margin_gap_pct" for r in results)  # only one branch
    assert not any(r.metric == "waste_to_revenue_pct" for r in results)  # no waste events
