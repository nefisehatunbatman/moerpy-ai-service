"""Financial Decision Knowledge Base.

Wraps KnowledgeBaseEntry persistence, seeding from data/financial_decisions.jsonl,
similarity search (via VectorStore), and the duplicate-detection used by the
approved-decision learning loop (spec section 23).
"""

import json
import hashlib
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger
from app.rag.embeddings import EmbeddingProvider
from app.rag.models import KnowledgeBaseEntry,LearningReceipt
from app.core.config import get_settings
from app.rag.vector_store import InMemoryCosineVectorStore, VectorMatch

logger = get_logger(__name__)

_SEED_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "financial_decisions.jsonl"
_DUPLICATE_SIMILARITY_THRESHOLD = 0.92


def _entry_text(problem_type: str, decision_type: str, decision_text: str) -> str:
    """Canonical text an entry is embedded from — keep this identical between
    seeding and later inserts so similarity comparisons are meaningful."""
    return f"{problem_type} {decision_type} {decision_text}"


class KnowledgeBaseRepository:
    def __init__(self, session: Session, embedding_provider: EmbeddingProvider,tenant_id='fixture-tenant') -> None:
        self.session = session
        self.tenant_id=tenant_id
        self.embedding_provider = embedding_provider
        self.vector_store = InMemoryCosineVectorStore()

    def seed_if_empty(self) -> None:
        if self.session.scalar(select(KnowledgeBaseEntry).limit(1)) is not None:
            return
        if not _SEED_FILE.exists():
            return
        with open(_SEED_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                self._insert(
                    entry_id=row["id"],
                    company_id=row.get("company_id"),
                    problem_type=row["problem_type"],
                    decision_type=row["decision_type"],
                    department=row.get("department", "finance"),
                    signals=row.get("signals", []),
                    conditions=row.get("conditions", {}),
                    decision_text=row["decision"],
                    financial_objective=row["financial_objective"],
                    expected_effect=row["expected_effect"],
                    approved=row.get("approved", True),
                    source=row.get("source", "initial"),
                )
        try: self.session.commit()
        except IntegrityError:
            self.session.rollback()
            if self.session.scalar(select(KnowledgeBaseEntry).limit(1)) is None: raise
        logger.info("knowledge_base_seeded", extra={"entries": self.session.query(KnowledgeBaseEntry).count()})

    def _insert(self, *, entry_id: str, **fields) -> KnowledgeBaseEntry:
        text = _entry_text(fields["problem_type"], fields["decision_type"], fields["decision_text"])
        embedding = self.embedding_provider.embed(text)
        entry = KnowledgeBaseEntry(id=entry_id, embedding=embedding,embedding_model=self.embedding_provider.identity,
            embedding_dimensions=len(embedding),tenant_id=self.tenant_id if fields.get('company_id') else None, **fields)
        self.session.add(entry)
        return entry

    def list_all(self, company_id: str | None = None) -> list[KnowledgeBaseEntry]:
        stmt = select(KnowledgeBaseEntry).where(KnowledgeBaseEntry.approved.is_(True))
        if company_id:
            stmt = stmt.where(
                (KnowledgeBaseEntry.company_id.is_(None) & KnowledgeBaseEntry.tenant_id.is_(None)) |
                ((KnowledgeBaseEntry.company_id == company_id) & (KnowledgeBaseEntry.tenant_id==self.tenant_id))
            )
        return list(self.session.scalars(stmt))

    def get(self, entry_id: str) -> KnowledgeBaseEntry | None:
        return self.session.get(KnowledgeBaseEntry, entry_id)

    def search(self, query_text: str, company_id: str | None, top_k: int = 3,problem_type=None, *, private_only=False) -> list[tuple[KnowledgeBaseEntry, float]]:
        query_embedding = self.embedding_provider.embed(query_text)
        candidates = self.list_all(company_id)
        if private_only:
            candidates = [c for c in candidates if c.company_id == company_id and c.tenant_id == self.tenant_id]
        if problem_type: candidates=[c for c in candidates if c.problem_type==problem_type]
        if any(c.embedding_model!=self.embedding_provider.identity or c.embedding_dimensions!=len(query_embedding) for c in candidates):
            raise ValueError('Embedding index version mismatch; run reindex before switching providers')
        pairs = [(c.id, c.embedding) for c in candidates]
        matches: list[VectorMatch] = self.vector_store.search(query_embedding, pairs, top_k)
        entries_by_id = {c.id: c for c in candidates}
        return [(entries_by_id[m.id],m.score) for m in matches if m.id in entries_by_id and m.score>=get_settings().rag_min_similarity]

    def reindex(self):
        entries=list(self.session.scalars(select(KnowledgeBaseEntry)))
        # Prepare all embeddings before mutating: a failed provider leaves the old index intact.
        vectors=[self.embedding_provider.embed(_entry_text(e.problem_type,e.decision_type,e.decision_text)) for e in entries]
        for entry,vector in zip(entries,vectors):
            entry.embedding=vector; entry.embedding_model=self.embedding_provider.identity; entry.embedding_dimensions=len(vector)
        self.session.commit()

    def find_duplicate(
        self, problem_type: str, decision_type: str, decision_text: str, company_id: str | None, *, private_only=False
    ) -> tuple[KnowledgeBaseEntry, float] | None:
        text = _entry_text(problem_type, decision_type, decision_text)
        matches = self.search(text, company_id, top_k=1, problem_type=problem_type, private_only=private_only)
        if not matches:
            return None
        entry, score = matches[0]
        if score >= _DUPLICATE_SIMILARITY_THRESHOLD:
            return entry, score
        return None

    def record_approved_decision(
        self,
        *,
        company_id: str,
        problem_type: str,
        decision_type: str,
        department: str,
        signals: list[str],
        conditions: dict,
        decision_text: str,
        financial_objective: str,
        expected_effect: str,
        source_decision_id: str | None = None,
    ) -> KnowledgeBaseEntry:
        """Approved decision learning (spec section 23): reuse a near-duplicate
        entry (bump counters, extend company_contexts) rather than inserting a
        fresh row every time the same kind of decision gets approved again.
        """
        if source_decision_id:
            receipt=self.session.get(LearningReceipt,source_decision_id)
            if receipt:
                entry = self.get(receipt.entry_id)
                if entry is None or entry.company_id != company_id or entry.tenant_id != self.tenant_id:
                    raise ValueError('Learning receipt is outside the authorized scope; migrate legacy learning first')
                return entry
        # Global templates are immutable shared examples, never company learning records.
        duplicate = self.find_duplicate(problem_type, decision_type, decision_text, company_id, private_only=True)
        if duplicate:
            entry, score = duplicate
            self.session.execute(update(KnowledgeBaseEntry).where(KnowledgeBaseEntry.id == entry.id).values(
                approval_count=KnowledgeBaseEntry.approval_count + 1,
                usage_count=KnowledgeBaseEntry.usage_count + 1,
                company_contexts=[company_id]))
            if source_decision_id: self.session.add(LearningReceipt(decision_id=source_decision_id,entry_id=entry.id))
            self.session.commit()
            logger.info(
                "knowledge_base_updated",
                extra={"entry_id": entry.id, "mode": "duplicate_reuse", "similarity": score},
            )
            return entry

        entry_key = json.dumps([self.tenant_id, company_id, problem_type, decision_type, decision_text], ensure_ascii=False)
        entry = self._insert(
            entry_id=f"KB-{hashlib.sha256(entry_key.encode()).hexdigest()}",
            company_id=company_id,
            problem_type=problem_type,
            decision_type=decision_type,
            department=department,
            signals=signals,
            conditions=conditions,
            decision_text=decision_text,
            financial_objective=financial_objective,
            expected_effect=expected_effect,
            approved=True,
            source="approved_decision",
        )
        entry.approval_count = 1
        entry.usage_count = 1
        entry.company_contexts = [company_id]
        if source_decision_id: self.session.add(LearningReceipt(decision_id=source_decision_id,entry_id=entry.id))
        self.session.commit()
        logger.info("knowledge_base_updated", extra={"entry_id": entry.id, "mode": "new_entry"})
        return entry
