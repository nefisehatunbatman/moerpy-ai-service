"""Vector store abstraction, decoupled from how embeddings are persisted.

InMemoryCosineVectorStore ranks whatever (id, embedding) pairs it's given —
today those come from KnowledgeBaseEntry.embedding via knowledge_base.py.
Swapping to Qdrant or pgvector later means implementing VectorStore once;
nothing in app/rag/retriever.py or app/llm changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.rag.embeddings import cosine_similarity


@dataclass(frozen=True)
class VectorMatch:
    id: str
    score: float


class VectorStore(ABC):
    @abstractmethod
    def search(self, query_embedding: list[float], candidates: list[tuple[str, list[float]]], top_k: int) -> list[VectorMatch]: ...


class InMemoryCosineVectorStore(VectorStore):
    def search(self, query_embedding: list[float], candidates: list[tuple[str, list[float]]], top_k: int) -> list[VectorMatch]:
        scored = [
            VectorMatch(id=entry_id, score=cosine_similarity(query_embedding, embedding))
            for entry_id, embedding in candidates
            if embedding
        ]
        scored.sort(key=lambda m: (-m.score, m.id))
        return scored[:top_k]
