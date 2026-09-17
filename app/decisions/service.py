"""Decision service â€” orchestrates the full pipeline from a persisted
anomaly to a Decision Card, and the approve/reject lifecycle transitions.
This is the only module that calls every other layer in sequence; it
contains no KPI/threshold/anomaly/confidence math of its own.
"""

import json
from datetime import datetime, timezone
from datetime import timedelta
from types import SimpleNamespace
import hashlib
from sqlalchemy import update,or_
from sqlalchemy.exc import IntegrityError
from app.kpi.models import KpiResult

from sqlalchemy.orm import Session

from app.anomaly.repository import AnomalyRepository
from app.confidence.engine import compute_confidence, confidence_reasons
from app.core.logging import get_logger
from app.data.models import Period
from app.data.providers.base import ERPDataProvider
from app.decisions.card import DecisionCard, ConfidenceOut, ExpectedImpactOut, RagOut, SignalOut, severity_label
from app.decisions.models import DecisionRecord
from app.decisions.repository import DecisionRepository
from app.evidence.builder import build_evidence
from app.financial_impact.analyzer import analyze
from app.kpi.labels import label_for
from app.llm.client import LLMClient
from app.llm.prompts import PROMPT_VERSION
from app.llm.decision_generator import generate_decision
from app.rag.embeddings import EmbeddingProvider
from app.rag.knowledge_base import KnowledgeBaseRepository
from app.rag.retriever import retrieve

logger = get_logger(__name__)


class DecisionNotFoundError(Exception):
    pass


class InvalidDecisionTransitionError(Exception):
    pass


def to_card(record: DecisionRecord) -> DecisionCard:
    return DecisionCard(
        **record.evidence_snapshot.get('executive_contract', {}),
        id=record.id,
        company_id=record.company_id,tenant_id=record.tenant_id,run_id=record.run_id,
        entity_id=record.evidence_snapshot.get('entity_id',''),entity_type=record.evidence_snapshot.get('entity_type',''),
        period=record.evidence_snapshot.get('period',{}),generator=record.generator_name,model_version=record.model_version,
        prompt_version=record.prompt_version,learning_status=record.learning_status,
        observed_impact=record.evidence_snapshot.get('quantified_impact'),
        language=record.evidence_snapshot.get('language','tr'),
        assessment_status=record.evidence_snapshot.get('assessment_status','review_required'),
        financial_areas=record.evidence_snapshot.get('financial_areas',[]),
        information_gaps=record.evidence_snapshot.get('information_gaps',[]),
        severity=record.severity,
        severity_label_tr=severity_label(record.severity),
        decision_type=record.decision_type,
        title=record.title,
        summary=record.summary,
        department=record.department,
        support_departments=record.support_departments,
        problem_signal=record.problem_signal,
        signals=[SignalOut(**s) for s in record.signals],
        recommended_decision=record.recommended_decision,
        reasoning=record.reasoning,
        expected_impact=[ExpectedImpactOut(**i) for i in record.expected_impact],
        confidence=ConfidenceOut(score=record.confidence_score,band=record.confidence_band,
            factors=record.confidence_factors,
            reasons=record.evidence_snapshot.get('confidence_reasons', [])),
        rag=RagOut(top_similarity=record.rag_top_similarity, matched_decision_ids=record.rag_matched_decision_ids),
        status=record.status,
    )


def generate_decision_for_anomaly(
    session: Session,
    *,
    company_id: str,
    anomaly_id: str,
    erp_provider: ERPDataProvider,
    llm_client: LLMClient,
    embedding_provider: EmbeddingProvider,
    language: str = 'tr',
) -> DecisionCard:
    anomaly_record = AnomalyRepository(session).get(anomaly_id)
    if anomaly_record is None or anomaly_record.company_id != company_id:
        raise DecisionNotFoundError(f"Anomaly not found: {anomaly_id}")
    anomaly = AnomalyRepository.to_schema(anomaly_record)
    if not anomaly_record.active:
        raise InvalidDecisionTransitionError('Anomaly has been superseded')
    if language not in ('tr','en'): raise ValueError('Unsupported language')
    decision_id='MOE-'+anomaly.period.start[2:4]+anomaly.period.start[5:7]+'-'+hashlib.sha256((anomaly.id+'|'+language+'|'+PROMPT_VERSION).encode()).hexdigest()[:24]
    existing=DecisionRepository(session).get(decision_id)
    if existing: return to_card(existing)

    period = Period(start=datetime.fromisoformat(anomaly.period.start).date(), end=datetime.fromisoformat(anomaly.period.end).date())
    if not anomaly_record.kpi_snapshot:
        raise InvalidDecisionTransitionError('Legacy anomaly has no verified snapshot; re-run analysis')
    kpis = [KpiResult.model_validate(k) for k in anomaly_record.kpi_snapshot]
    impact = analyze(anomaly, kpis)

    thresholds = [SimpleNamespace(**t) for t in anomaly_record.threshold_snapshot]
    evidence = build_evidence(anomaly, impact, kpis, thresholds)
    evidence=evidence.model_copy(update={'language':language,'signals':[s.model_copy(update={'label':label_for(s.metric,language)}) for s in evidence.signals]})

    kb_repo = KnowledgeBaseRepository(session, embedding_provider,anomaly.tenant_id)
    kb_repo.seed_if_empty()
    retrieved = retrieve(kb_repo, evidence, top_k=3)

    llm_output = generate_decision(evidence, retrieved, llm_client)
    confidence = compute_confidence(evidence, anomaly.severity, retrieved)
    evidence = evidence.model_copy(update={'confidence_reasons': confidence_reasons(evidence, confidence.factors)})

    decision_repo = DecisionRepository(session)

    expected_impact_out = [
        ExpectedImpactOut(
            metric=i.metric, label=label_for(i.metric,language), direction=i.direction, type=i.type, value=i.value, unit=i.unit
        ).model_dump()
        for i in llm_output.expected_impact
    ]
    signals_out = [
        SignalOut(metric=s.metric, label=s.label, value=s.value, unit=s.unit,
                  entity_id=s.entity_id, entity_type=s.entity_type,
                  selection_reason=s.selection_reason, scope_relation=s.scope_relation).model_dump() for s in evidence.signals
    ]

    from app.decisions.executive import project
    executive = project(evidence)
    executive['traceability']['decision_id'] = decision_id
    executive['traceability']['confidence'] = dict(source_type='DETERMINISTIC_METRIC',
        calculation_source='app/confidence/engine.py', score=confidence.score,
        factors=confidence.factors.model_dump(), interpretation='heuristic_evidence_sufficiency_not_probability')
    snapshot = json.loads(evidence.model_dump_json())
    snapshot['executive_contract'] = {k: executive[k] for k in (
        'decision_readiness', 'action_id', 'action_policy_source', 'blockers', 'risks',
        'do_not_apply_when', 'success_metric', 'impact_assessment', 'traceability')}
    record = DecisionRecord(
        id=decision_id,
        company_id=company_id,
        tenant_id=anomaly.tenant_id,run_id=anomaly.run_id,
        model_version=getattr(llm_client,'model_version',llm_client.generator_name),prompt_version=PROMPT_VERSION,
        confidence_factors=confidence.factors.model_dump(),
        anomaly_id=anomaly.id,
        severity=anomaly.severity,
        decision_type=llm_output.decision_type,
        problem_type=evidence.problem_type,
        financial_objective=evidence.financial_objective,
        title=llm_output.title,
        summary=llm_output.summary,
        problem_signal=llm_output.problem_signal,
        recommended_decision=llm_output.recommended_decision,
        reasoning=llm_output.reasoning,
        expected_impact=expected_impact_out,
        department=llm_output.department,
        support_departments=llm_output.support_departments,
        signals=signals_out,
        confidence_score=confidence.score,
        confidence_band=confidence.band,
        rag_top_similarity=retrieved[0].similarity if retrieved else 0.0,
        rag_matched_decision_ids=[r.id for r in retrieved],
        evidence_snapshot=snapshot,
        rag_snapshot=[json.loads(r.model_dump_json()) for r in retrieved],
        generator_name=llm_client.generator_name,
        status="PROPOSED",
    )
    try:
        decision_repo.add(record)
    except IntegrityError:
        session.rollback()
        existing=decision_repo.get(decision_id)
        if existing: return to_card(existing)
        raise

    logger.info("decision_generated", extra={"decision_id": record.id, "company_id": company_id, "anomaly_id": anomaly_id})
    return to_card(record)


def approve_decision(
    session: Session, *, decision_id: str, actor: str, note: str | None, embedding_provider: EmbeddingProvider
) -> DecisionCard:
    decision_repo = DecisionRepository(session)
    record = decision_repo.get(decision_id)
    if record is None:
        raise DecisionNotFoundError(decision_id)
    if record.status != "PROPOSED":
        raise InvalidDecisionTransitionError(f"Cannot approve a decision in status {record.status}")
    readiness = record.evidence_snapshot.get('executive_contract', {}).get('decision_readiness')
    if readiness not in ('control_plan_only',):
        raise InvalidDecisionTransitionError('Decision evidence or action policy is insufficient; regenerate after correction')

    decision_repo.transition(record,'APPROVED',actor=actor,note=note,
        approved_at=datetime.now(timezone.utc),approved_by=actor,learning_status='pending')
    retry_learning(session,record,embedding_provider)

    logger.info("decision_approved", extra={"decision_id": record.id, "actor": actor})
    return to_card(record)


def reject_decision(session: Session, *, decision_id: str, actor: str, reason: str | None) -> DecisionCard:
    decision_repo = DecisionRepository(session)
    record = decision_repo.get(decision_id)
    if record is None:
        raise DecisionNotFoundError(decision_id)
    if record.status != "PROPOSED":
        raise InvalidDecisionTransitionError(f"Cannot reject a decision in status {record.status}")

    decision_repo.transition(record,'REJECTED',actor=actor,note=reason,
        rejected_at=datetime.now(timezone.utc),rejected_by=actor,rejection_reason=reason)

    # Deliberately does NOT touch the knowledge base â€” rejected decisions never
    # become learned patterns (spec section 23).
    logger.info("decision_rejected", extra={"decision_id": record.id, "actor": actor})
    return to_card(record)


def _expected_effect_text(expected_impact: list[dict]) -> str:
    if not expected_impact:
        return "Beklenen etki verisi bulunmuyor."
    parts = []
    for item in expected_impact:
        direction_tr = {"increase": "artış", "decrease": "azalış", "stabilize": "stabilizasyon"}.get(
            item["direction"], item["direction"]
        )
        parts.append(f"{label_for(item['metric'])} için {direction_tr} beklenmektedir.")
    return " ".join(parts)


def retry_learning(session,record,embedding_provider):
    if record.status!='APPROVED':
        raise InvalidDecisionTransitionError('Only approved decisions can enter learning')
    now=datetime.now(timezone.utc)
    claim=session.execute(update(DecisionRecord).where(DecisionRecord.id==record.id,
        or_(DecisionRecord.learning_status.in_(['pending','failed']),
            (DecisionRecord.learning_status=='processing') & (DecisionRecord.learning_started_at<now-timedelta(minutes=5))))
        .values(learning_status='processing',learning_started_at=now),execution_options={'synchronize_session':False})
    session.commit()
    if claim.rowcount!=1:
        session.refresh(record)
        return
    try:
        KnowledgeBaseRepository(session,embedding_provider,record.tenant_id).record_approved_decision(
            company_id=record.company_id,problem_type=record.problem_type,decision_type=record.decision_type,
            department=record.department,signals=[s['metric'] for s in record.signals],
            conditions={'period':record.evidence_snapshot.get('period'),'run_id':record.run_id},
            decision_text=record.recommended_decision,financial_objective=record.financial_objective,
            expected_effect=_expected_effect_text(record.expected_impact),source_decision_id=record.id)
        session.execute(update(DecisionRecord).where(DecisionRecord.id==record.id,
            DecisionRecord.learning_status=='processing', DecisionRecord.learning_started_at==now)
            .values(learning_status='completed',learning_error=None),execution_options={'synchronize_session':False})
        session.commit()
        session.refresh(record)
    except Exception as exc:
        session.rollback()
        session.refresh(record)
        session.execute(update(DecisionRecord).where(DecisionRecord.id==record.id,
            DecisionRecord.learning_status=='processing', DecisionRecord.learning_started_at==now)
            .values(learning_status='failed',learning_error=type(exc).__name__),execution_options={'synchronize_session':False})
        session.commit()
        session.refresh(record)
        logger.warning('learning_failed',extra={'decision_id':record.id,'error_type':type(exc).__name__})

