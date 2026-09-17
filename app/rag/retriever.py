"""RAG retrieval: EvidencePackage -> query text -> embedding -> vector search
-> top-k historical financial decisions. Kept separate from app/llm so the
LLM client never has to know how retrieval works.
"""

from pydantic import BaseModel

from app.core.logging import get_logger
from app.evidence.models import EvidencePackage
from app.rag.knowledge_base import KnowledgeBaseRepository

logger = get_logger(__name__)


class RetrievedDecision(BaseModel):
    id: str
    decision_text: str
    decision_type: str
    problem_type: str
    financial_objective: str
    expected_effect: str
    similarity: float
    source: str = 'initial'


def _query_text(evidence: EvidencePackage) -> str:
    signal_labels = " ".join(s.label for s in evidence.signals)
    return f"{evidence.problem_type} {' '.join(evidence.financial_areas)} {evidence.financial_objective} {signal_labels}"


def retrieve(kb: KnowledgeBaseRepository, evidence: EvidencePackage, top_k: int = 3) -> list[RetrievedDecision]:
    query = _query_text(evidence)
    matches = kb.search(query,company_id=evidence.company_id,top_k=top_k,problem_type=evidence.problem_type)

    results = [
        RetrievedDecision(
            id=entry.id,
            decision_text=entry.decision_text,
            decision_type=entry.decision_type,
            problem_type=entry.problem_type,
            financial_objective=entry.financial_objective,
            expected_effect=entry.expected_effect,
            similarity=round(score, 4),
            source=entry.source,
        )
        for entry, score in matches
    ]
    logger.info(
        "rag_search_performed",
        extra={"anomaly_id": evidence.anomaly_id, "matched": [r.id for r in results]},
    )
    return results
