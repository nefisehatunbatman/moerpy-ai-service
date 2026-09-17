from functools import lru_cache

from app.core.config import get_settings
from app.data.providers.base import ERPDataProvider
from app.data.providers.fake_provider import FakeERPDataProvider


@lru_cache
def get_erp_provider() -> ERPDataProvider:
    settings = get_settings()
    if settings.erp_provider == 'business':
        from app.data.providers.business_provider import BusinessERPProvider
        return BusinessERPProvider(settings.business_dataset_db)
    if settings.erp_provider == "postgres":
        if not settings.erp_database_url:
            raise RuntimeError("ERP_PROVIDER=postgres requires ERP_DATABASE_URL to be set.")
        from app.data.providers.postgres_provider import PostgresERPProvider

        return PostgresERPProvider(settings.erp_database_url)
    return FakeERPDataProvider()
