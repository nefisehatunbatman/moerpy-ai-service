from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.data.factory import get_erp_provider
from app.data.providers.base import ERPDataProvider
from app.db.base import SessionLocal
from app.llm.client import LLMClient, get_llm_client
from app.rag.embeddings import EmbeddingProvider, get_embedding_provider


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_provider() -> ERPDataProvider:
    return get_erp_provider()


def get_llm() -> LLMClient:
    return get_llm_client()


def get_embedder() -> EmbeddingProvider:
    return get_embedding_provider()
