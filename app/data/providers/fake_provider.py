"""Deterministic fixture-backed ERPDataProvider.

Reads app/data/fixtures/*.json — a hand-built dataset shaped exactly like
the real Supabase canonical/fact tables (see supabase/migrations). Two
companies: COMP-001 has several engineered financial problems (margin
compression, unit-cost overrun, overstock, waste), COMP-002 is a clean
comparison company with no anomalies, so company-specific thresholds can
be demonstrated. No value here is invented at query time — every number
returned is read verbatim from these files.
"""

import json
from datetime import date
from pathlib import Path

from app.data.models import (
    Company,
    CostFact,
    InventoryFact,
    Period,
    Product,
    SalesFact,
    Store,
    WasteReturnFact,
)
from app.data.providers.base import ERPDataProvider
from app.core.errors import InvalidPeriodError

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load(name: str) -> list[dict]:
    with open(_FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _lineage(row):
    # Fixture defaults belong here, never in the production data contracts.
    return dict(tenant_id=row.get('tenant_id', 'fixture-tenant'),
                import_batch_id=row.get('import_batch_id', 'fixture-v1'),
                source_system=row.get('source_system', 'fixture'),
                variant_id=row.get('variant_id'))


def _optional_date(row, key):
    return date.fromisoformat(row[key]) if row.get(key) else None


class FakeERPDataProvider(ERPDataProvider):
    def __init__(self) -> None:
        self._companies = {c['id']: Company(**{'tenant_id': 'fixture-tenant', **c}) for c in _load('companies.json')}
        self._stores = [Store(**s) for s in _load("stores.json")]
        self._products = [Product(**p) for p in _load("products.json")]
        self._sales_facts = [self._parse_sales_fact(r) for r in _load("sales_facts.json")]
        self._cost_facts = [self._parse_cost_fact(r) for r in _load("cost_facts.json")]
        self._inventory_facts = [self._parse_inventory_fact(r) for r in _load("inventory_facts.json")]
        self._waste_return_facts = [self._parse_waste_return_fact(r) for r in _load("waste_return_facts.json")]

    @staticmethod
    def _parse_sales_fact(r: dict) -> SalesFact:
        period = Period(start=date.fromisoformat(r["period_start"]), end=date.fromisoformat(r["period_end"]))
        return SalesFact(
            id=r["id"],
            company_id=r["company_id"],
            store_id=r["store_id"],
            product_id=r["product_id"],
            period=period,
            quantity_sold=r["quantity_sold"],
            revenue=r["revenue"],
            discount=r["discount"],
            unit_cost=r.get('unit_cost'),
            sales_date=_optional_date(r, 'sales_date'),
            cogs_amount=r.get('cogs_amount'),
            cost_basis_known=r.get('cost_basis_known', True),
            **_lineage(r),
        )

    @staticmethod
    def _parse_cost_fact(r: dict) -> CostFact:
        period = Period(start=date.fromisoformat(r["period_start"]), end=date.fromisoformat(r["period_end"]))
        return CostFact(
            id=r["id"],
            company_id=r["company_id"],
            product_id=r["product_id"],
            period=period,
            standard_unit_cost=r["standard_unit_cost"],
            currency=r["currency"],
            supplier=r["supplier"],
            is_budget=r.get('is_budget', True),
            store_id=r.get('store_id'),
            effective_date=_optional_date(r, 'effective_date'),
            effective_to=_optional_date(r, 'effective_to'),
            **_lineage(r),
        )

    @staticmethod
    def _parse_inventory_fact(r: dict) -> InventoryFact:
        return InventoryFact(
            id=r["id"],
            company_id=r["company_id"],
            store_id=r["store_id"],
            product_id=r["product_id"],
            snapshot_date=date.fromisoformat(r["snapshot_date"]),
            quantity=r["quantity"],
            unit_cost=r.get('unit_cost'),
            inventory_value=r.get('inventory_value'),
            **_lineage(r),
        )

    @staticmethod
    def _parse_waste_return_fact(r: dict) -> WasteReturnFact:
        return WasteReturnFact(
            id=r["id"],
            company_id=r["company_id"],
            store_id=r["store_id"],
            product_id=r["product_id"],
            event_date=date.fromisoformat(r["event_date"]),
            event_type=r["event_type"],
            quantity=r["quantity"],
            reason=r["reason"],
            cost_amount=r.get("cost_amount"),
            cost_basis_known=r.get('cost_basis_known', True),
            **_lineage(r),
        )

    def list_companies(self) -> list[Company]:
        return list(self._companies.values())

    def get_company(self, company_id: str) -> Company | None:
        return self._companies.get(company_id)

    def list_stores(self, company_id: str) -> list[Store]:
        return [s for s in self._stores if s.company_id == company_id]

    def list_products(self, company_id: str) -> list[Product]:
        return [p for p in self._products if p.company_id == company_id]

    def get_sales_facts(self, company_id: str, period: Period) -> list[SalesFact]:
        for fact in self._sales_facts:
            if (fact.company_id == company_id and fact.sales_date is None and _overlaps(fact.period, period)
                    and not (period.start <= fact.period.start and fact.period.end <= period.end)):
                raise InvalidPeriodError('Partial fixture period: monthly totals cannot be split into daily sales')
        return [
            f
            for f in self._sales_facts
            if f.company_id == company_id and (
                period.start <= f.sales_date <= period.end if f.sales_date is not None
                else period.start <= f.period.start and f.period.end <= period.end)
        ]

    def get_cost_facts(self, company_id: str, period: Period) -> list[CostFact]:
        return [
            f
            for f in self._cost_facts
            if f.company_id == company_id and _overlaps(f.period, period)
        ]

    def get_inventory_facts(self, company_id: str, as_of: date) -> list[InventoryFact]:
        rows = [f for f in self._inventory_facts if f.company_id == company_id and f.snapshot_date <= as_of]
        latest = {}
        for f in sorted(rows, key=lambda r: (r.snapshot_date, r.id)):
            latest[(f.store_id, f.product_id, f.variant_id)] = f
        return list(latest.values())

    def get_waste_return_facts(self, company_id: str, period: Period) -> list[WasteReturnFact]:
        return [
            f
            for f in self._waste_return_facts
            if f.company_id == company_id and period.start <= f.event_date <= period.end
        ]


def _overlaps(a: Period, b: Period) -> bool:
    return a.start <= b.end and b.start <= a.end
