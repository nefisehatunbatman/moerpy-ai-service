"""Move legacy global-template learning into private company records, without model calls."""
import hashlib
import json

from sqlalchemy import select

from app.decisions.models import DecisionRecord
from app.rag.models import KnowledgeBaseEntry, LearningReceipt


def repair_global_learning(session):
    templates = list(session.scalars(select(KnowledgeBaseEntry).where(
        KnowledgeBaseEntry.company_id.is_(None), KnowledgeBaseEntry.tenant_id.is_(None))))
    for template in templates:
        receipts = list(session.scalars(select(LearningReceipt).where(LearningReceipt.entry_id == template.id)))
        for receipt in receipts:
            decision = session.get(DecisionRecord, receipt.decision_id)
            if decision is None or not decision.company_id or decision.tenant_id in (None, '', 'legacy-unscoped'):
                raise ValueError('Cannot scope legacy learning receipt: restore tenant/company ownership before migration')
            key = json.dumps([decision.tenant_id, decision.company_id, template.problem_type,
                              template.decision_type, template.decision_text], ensure_ascii=False)
            entry_id = 'KB-' + hashlib.sha256(key.encode()).hexdigest()
            private = session.get(KnowledgeBaseEntry, entry_id)
            if private is None:
                private = KnowledgeBaseEntry(
                    id=entry_id, tenant_id=decision.tenant_id, company_id=decision.company_id,
                    problem_type=template.problem_type, decision_type=template.decision_type,
                    department=template.department, signals=template.signals, conditions=template.conditions,
                    decision_text=template.decision_text, financial_objective=template.financial_objective,
                    expected_effect=template.expected_effect, approved=True, source='approved_decision',
                    approval_count=0, usage_count=0, company_contexts=[decision.company_id],
                    embedding=list(template.embedding), embedding_model=template.embedding_model,
                    embedding_dimensions=template.embedding_dimensions)
                session.add(private)
                session.flush()
            private.approval_count += 1
            private.usage_count += 1
            receipt.entry_id = entry_id
        # Global templates never publish company membership or private activity counters.
        template.company_contexts = []
        template.approval_count = 0
        template.usage_count = 0
    session.flush()
