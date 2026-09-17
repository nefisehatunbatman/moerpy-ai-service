from functools import lru_cache
from typing import Literal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import model_validator, field_validator, Field
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ROOT = Path(__file__).resolve().parents[2]


def resolved_path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else SERVICE_ROOT / path).resolve()


def memory_database(url):
    return url.get_backend_name() == 'sqlite' and (
        not url.database or url.database in (':memory:', 'file::memory:')
        or url.query.get('mode') == 'memory')


def database_identity(url):
    backend = url.get_backend_name().replace('postgresql', 'postgres')
    if backend == 'sqlite':
        if memory_database(url):
            return ('sqlite-memory',)
        return ('sqlite', resolved_path(url.database.removeprefix('file:')))
    host = (url.host or '').lower().rstrip('.')
    if host in ('localhost', '127.0.0.1', '::1'):
        host = 'loopback'
    return backend, host, url.port or (5432 if backend == 'postgres' else None), url.database


class Settings(BaseSettings):
    """Central configuration. All values come from environment / .env — never hardcoded."""

    model_config = SettingsConfigDict(env_file=SERVICE_ROOT / '.env', extra='ignore', hide_input_in_errors=True)

    ai_service_api_prefix: str = "/api/v1"
    ai_service_log_level: Literal['DEBUG','INFO','WARNING','ERROR','CRITICAL'] = 'INFO'
    ai_service_internal_token: str | None = Field(default=None, repr=False)
    reporting_timezone: str = 'Europe/Istanbul'
    environment: Literal['development', 'test', 'production'] = 'development'
    context_max_age_seconds: int = Field(default=120,ge=1,le=300)
    max_request_bytes: int = Field(default=32768,ge=1024,le=1048576)
    max_concurrent_requests: int = Field(default=8,ge=1,le=64)
    inventory_max_age_days: int = Field(default=7,ge=0,le=31)
    llm_timeout_seconds: float = Field(default=20,gt=0,le=60)
    llm_max_tokens: int = Field(default=1600,ge=100,le=4096)
    rag_min_similarity: float = Field(default=0.15,ge=0,le=1)
    business_dataset_db: str = './data/business_24m.db'

    erp_provider: Literal['fake', 'postgres', 'business'] = 'fake'
    erp_database_url: str | None = Field(default=None, repr=False)

    ai_service_database_url: str = Field(default='sqlite:///./data/service_v2.db', repr=False)

    llm_api_key: str | None = Field(default=None, repr=False)
    llm_mode: Literal['offline','live'] = 'offline'
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"

    embedding_api_key: str | None = Field(default=None, repr=False)
    embedding_mode: Literal['local','live'] = 'local'
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"

    @field_validator('reporting_timezone')
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('REPORTING_TIMEZONE must be an installed IANA timezone') from None
        return value

    @field_validator('business_dataset_db')
    @classmethod
    def dataset_path(cls, value):
        return str(resolved_path(value))

    @field_validator('ai_service_database_url', 'erp_database_url')
    @classmethod
    def normalize_url(cls, value, info):
        if not value:
            if info.field_name == 'ai_service_database_url':
                raise ValueError('AI_SERVICE_DATABASE_URL is required')
            return value
        try:
            url = make_url(value)
            if url.get_backend_name() == 'sqlite' and not memory_database(url):
                uri = url.database.startswith('file:')
                path = resolved_path(url.database.removeprefix('file:')).as_posix()
                url = url.set(database=('file:' if uri else '') + path)
            return url.render_as_string(hide_password=False)
        except (ArgumentError, ValueError, TypeError):
            raise ValueError('Invalid database URL') from None

    @model_validator(mode='after')
    def validate_runtime(self):
        if not self.ai_service_api_prefix.startswith('/') or self.ai_service_api_prefix == '/' or self.ai_service_api_prefix.endswith('/'):
            raise ValueError('AI_SERVICE_API_PREFIX must be a non-root absolute path without a trailing slash')
        if self.erp_provider == 'postgres' and not self.erp_database_url:
            raise ValueError('ERP_PROVIDER=postgres requires ERP_DATABASE_URL')
        ai_url = make_url(self.ai_service_database_url)
        if self.erp_database_url:
            erp_url = make_url(self.erp_database_url)
            if database_identity(ai_url) == database_identity(erp_url):
                raise ValueError('AI state database must be separate from the read-only ERP database')
        if (ai_url.get_backend_name() == 'sqlite' and not memory_database(ai_url)
                and database_identity(ai_url)[1] == resolved_path(self.business_dataset_db)):
            raise ValueError('AI state database must be separate from the business dataset')
        if self.llm_mode=='live' and not self.llm_api_key:
            raise ValueError('LLM_MODE=live requires LLM_API_KEY')
        if self.embedding_mode=='live' and not self.embedding_api_key:
            raise ValueError('EMBEDDING_MODE=live requires EMBEDDING_API_KEY')
        if self.environment == 'production':
            if not self.ai_service_internal_token or len(self.ai_service_internal_token) < 32:
                raise ValueError('Production requires a strong internal token (32+ characters)')
            if self.erp_provider == 'fake':
                raise ValueError('Production cannot use fixture ERP data')
            if memory_database(ai_url):
                raise ValueError('Production requires a persistent AI database')
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
