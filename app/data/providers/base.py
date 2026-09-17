"""ERPDataProvider abstraction.

The rest of the AI service (KPI engine, thresholds, anomaly detection, ...)
depends only on this interface, never on a concrete storage format. Today
FakeERPDataProvider backs it; PostgresERPProvider can replace it later
without touching any downstream code.
"""

from abc import ABC, abstractmethod
from datetime import date

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


class ERPDataProvider(ABC):
    @abstractmethod
    def list_companies(self) -> list[Company]: ...

    @abstractmethod
    def get_company(self, company_id: str) -> Company | None: ...

    @abstractmethod
    def list_stores(self, company_id: str) -> list[Store]: ...

    @abstractmethod
    def list_products(self, company_id: str) -> list[Product]: ...

    @abstractmethod
    def get_sales_facts(self, company_id: str, period: Period) -> list[SalesFact]: ...

    @abstractmethod
    def get_cost_facts(self, company_id: str, period: Period) -> list[CostFact]: ...

    @abstractmethod
    def get_inventory_facts(self, company_id: str, as_of: date) -> list[InventoryFact]: ...

    @abstractmethod
    def get_waste_return_facts(self, company_id: str, period: Period) -> list[WasteReturnFact]: ...
