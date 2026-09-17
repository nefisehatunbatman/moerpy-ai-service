from datetime import date

from app.data.models import Period
from app.data.providers.fake_provider import FakeERPDataProvider

FEB = Period(start=date(2026, 2, 1), end=date(2026, 2, 28))


def test_lists_two_companies():
    provider = FakeERPDataProvider()
    companies = {c.id for c in provider.list_companies()}
    assert companies == {"COMP-001", "COMP-002"}


def test_comp001_sales_facts_period_totals():
    provider = FakeERPDataProvider()
    facts = provider.get_sales_facts("COMP-001", FEB)
    assert len(facts) == 6
    assert sum(f.revenue for f in facts) == 1_025_000


def test_comp002_has_no_waste_events():
    provider = FakeERPDataProvider()
    facts = provider.get_waste_return_facts("COMP-002", FEB)
    assert facts == []
