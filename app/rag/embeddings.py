"""Embedding provider abstraction.

LocalHashEmbedding is the default: deterministic, offline, no API key
required — good enough to demonstrate retrieval over a small knowledge
base. OpenAICompatibleEmbedding is selected by EMBEDDING_MODE=live,
which also requires an API key and a compatible/rebuilt index.
"""

import hashlib
import math
import re
from abc import ABC, abstractmethod

from app.core.config import get_settings

_DIMENSIONS = 256
_TOKEN_RE = re.compile(r"[a-zçğıöşü0-9]+", re.IGNORECASE)


class EmbeddingProvider(ABC):
    @property
    def identity(self):
        return self.__class__.__name__ + ':' + getattr(self,'_model','hash-v1-256')
    @abstractmethod
    def embed(self, text: str) -> list[float]: ...


class LocalHashEmbedding(EmbeddingProvider):
    """Hashing-based bag-of-words vector. Deterministic: the same text
    always produces the same vector, and texts sharing more tokens end up
    with higher cosine similarity — enough for a small, curated knowledge
    base without any network dependency.
    """

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * _DIMENSIONS
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % _DIMENSIONS
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]


class OpenAICompatibleEmbedding(EmbeddingProvider):
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model

    def embed(self, text: str) -> list[float]:
        from app.llm.transport import post_json,ProviderError
        response=post_json(f'{self._base_url}/embeddings',self._api_key,{'model':self._model,'input':text})
        try:
            vector=response['data'][0]['embedding']
            if not isinstance(vector,list) or not vector or not all(type(v) in (int,float) and math.isfinite(v) for v in vector): raise ValueError()
            if not any(v != 0 for v in vector): raise ValueError()
            return vector
        except (ValueError,KeyError,TypeError,IndexError) as exc:
            raise ProviderError('Invalid embedding response') from exc


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedding_mode=='live':
        return OpenAICompatibleEmbedding(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
        )
    return LocalHashEmbedding()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a)!=len(b):
        raise ValueError('Embedding dimension mismatch; rebuild the index')
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
