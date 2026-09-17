"""Canonical ERP data shapes.

These mirror the real Supabase schema (supabase/migrations) so that
FakeERPDataProvider and PostgresERPProvider are interchangeable: same
fields, same meaning, only the storage differs.
"""

from dataclasses import dataclass
from datetime import date
from app.core.errors import InvalidPeriodError, InvalidSourceDataError


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    def __post_init__(self):
        if self.end < self.start:
            raise InvalidPeriodError('period_end must be on or after period_start')
        if (self.end - self.start).days > 1095:
            raise InvalidPeriodError('Period cannot exceed three years')

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True)
class Company:
    id: str
    name: str
    currency: str
    tenant_id: str

    def __post_init__(self):
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise InvalidSourceDataError('Company tenant_id is required')


@dataclass(frozen=True, kw_only=True)
class Lineage:
    tenant_id: str
    import_batch_id: str = 'fixture-v1'
    variant_id: str | None = None  # fake data icin version takip vs icin
    source_system: str = 'fixture'  # hangi erp kaynagi sap,erp,logo,netsis

    def __post_init__(self):
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise InvalidSourceDataError('Fact tenant_id is required')


@dataclass(frozen=True)
class Store:
    id: str
    company_id: str
    code: str
    name: str
    region: str
    city: str


@dataclass(frozen=True)
class Product:
    id: str
    company_id: str
    code: str
    name: str
    category: str
    unit_of_measure: str


@dataclass(frozen=True)
class SalesFact(Lineage):
    id: str
    company_id: str
    store_id: str
    product_id: str
    period: Period
    quantity_sold: float
    revenue: float
    discount: float
    unit_cost: float | None
    sales_date: date | None = None
    cogs_amount: float | None = None
    cost_basis_known: bool = True


@dataclass(frozen=True)
class CostFact(Lineage):
    id: str
    company_id: str
    product_id: str
    period: Period
    standard_unit_cost: float  # budgeted/standard cost from the Cost Upload — the variance baseline
    currency: str
    supplier: str
    store_id: str | None = None
    effective_date: date | None = None
    effective_to: date | None = None
    is_budget: bool = False  # An observed cost is never implicitly an approved budget.

    def __post_init__(self):
        super().__post_init__()
        if self.effective_to is not None and self.effective_to < (self.effective_date or self.period.start):
            raise InvalidSourceDataError('Cost effective_to precedes effective_date')


@dataclass(frozen=True)
class InventoryFact(Lineage):
    id: str
    company_id: str
    store_id: str
    product_id: str
    snapshot_date: date
    quantity: float
    unit_cost: float | None
    inventory_value: float | None = None


@dataclass(frozen=True)
class WasteReturnFact(Lineage):
    id: str
    company_id: str
    store_id: str
    product_id: str
    event_date: date
    event_type: str  # "waste" | "return"
    quantity: float
    reason: str
    cost_amount: float | None = None
    cost_basis_known: bool = True

    def __post_init__(self):
        super().__post_init__()
        if self.event_type not in ('waste', 'return'):
            raise InvalidSourceDataError('Unknown waste/return event_type')
