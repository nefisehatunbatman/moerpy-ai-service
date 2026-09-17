"""Scoped API contract. Every resource lookup is checked against signed caller context."""
from datetime import date
from typing import Literal
from fastapi import APIRouter,Depends,Request,HTTPException,Query
from pydantic import BaseModel,model_validator,Field
from sqlalchemy.orm import Session
from app.api.deps import get_db,get_provider,get_llm,get_embedder
from app.api.security import scope_for,require_company,require_record,require_role
from app.data.models import Period
from app.core.dates import reporting_today
from app.core.errors import InvalidPeriodError
from app.kpi.engine import compute_kpis
from app.anomaly.detector import detect_anomalies
from app.anomaly.repository import AnomalyRepository
from app.thresholds.repository import ThresholdRepository
from app.thresholds.defaults import get_seed_thresholds
from app.thresholds.schemas import ThresholdIn,ThresholdOut
from app.decisions.repository import DecisionRepository
from app.decisions.card import DecisionCard
from app.anomaly.schemas import Anomaly
from app.kpi.models import KpiResult
from app.evidence.models import EvidencePackage
from app.rag.retriever import RetrievedDecision
from app.decisions.service import generate_decision_for_anomaly,approve_decision,reject_decision,to_card,retry_learning

router=APIRouter()

def validated_period(start: date, end: date) -> Period:
    if end > reporting_today():
        raise InvalidPeriodError('period_end cannot be in the future; use the actual reporting cutoff')
    return Period(start, end)

class AnalysisRequest(BaseModel):
    company_id: str = Field(min_length=1,max_length=200)
    period_start: date
    period_end: date
    @model_validator(mode='after')
    def dates(self):
        validated_period(self.period_start,self.period_end)
        return self

class TransitionRequest(BaseModel):
    actor: str | None = None  # ignored: actor always comes from authenticated context
    note: str | None = Field(default=None,max_length=2000)
    reason: str | None = Field(default=None,max_length=2000)

@router.get('/companies/{company_id}/kpis',response_model=list[KpiResult])
def kpis(company_id:str,request:Request,period_start:date,period_end:date,provider=Depends(get_provider)):
    require_company(scope_for(request),company_id,provider)
    return compute_kpis(provider,company_id,validated_period(period_start,period_end))

@router.get('/companies/{company_id}/thresholds',response_model=list[ThresholdOut])
def thresholds(company_id:str,request:Request,provider=Depends(get_provider),session:Session=Depends(get_db)):
    require_company(scope_for(request),company_id,provider)
    repo=ThresholdRepository(session,scope_for(request).tenant_id)
    repo.seed_if_empty(company_id,get_seed_thresholds(company_id))
    return [ThresholdOut.model_validate(t) for t in repo.list_for_company(company_id,active_only=False)]

@router.put('/companies/{company_id}/thresholds',response_model=ThresholdOut)
def put_threshold(company_id:str,body:ThresholdIn,request:Request,provider=Depends(get_provider),session:Session=Depends(get_db)):
    require_company(scope_for(request),company_id,provider); require_role(scope_for(request))
    repo=ThresholdRepository(session,scope_for(request).tenant_id)
    repo.seed_if_empty(company_id,get_seed_thresholds(company_id))
    return ThresholdOut.model_validate(repo.upsert(company_id,body))

@router.post('/analysis/run',response_model=list[Anomaly])
def analysis(body:AnalysisRequest,request:Request,provider=Depends(get_provider),session:Session=Depends(get_db)):
    require_company(scope_for(request),body.company_id,provider)
    require_role(scope_for(request))
    period=Period(body.period_start,body.period_end)
    repo=ThresholdRepository(session,scope_for(request).tenant_id)
    repo.seed_if_empty(body.company_id,get_seed_thresholds(body.company_id))
    results=compute_kpis(provider,body.company_id,period)
    anomalies=detect_anomalies(body.company_id,period,results,repo.list_for_company(body.company_id))
    AnomalyRepository(session).save_all(anomalies,body.company_id,period,scope_for(request).tenant_id)
    return anomalies

@router.get('/companies/{company_id}/anomalies',response_model=list[Anomaly])
def anomalies(company_id:str,request:Request,provider=Depends(get_provider),session:Session=Depends(get_db),limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0)):
    require_company(scope_for(request),company_id,provider)
    return [AnomalyRepository.to_schema(r) for r in AnomalyRepository(session).list_for_company(company_id,limit,offset,scope_for(request).tenant_id)]

@router.get('/anomalies/{anomaly_id}',response_model=Anomaly)
def anomaly(anomaly_id:str,request:Request,session:Session=Depends(get_db)):
    return AnomalyRepository.to_schema(require_record(scope_for(request),AnomalyRepository(session).get(anomaly_id)))

@router.post('/anomalies/{anomaly_id}/generate-decision',response_model=DecisionCard)
def generate(anomaly_id:str,request:Request,language:Literal['tr','en']='tr',provider=Depends(get_provider),session:Session=Depends(get_db),llm=Depends(get_llm),embedder=Depends(get_embedder)):
    record=require_record(scope_for(request),AnomalyRepository(session).get(anomaly_id))
    require_role(scope_for(request))
    if not record.active: raise HTTPException(409,'Anomaly has been superseded; run a current analysis')
    return generate_decision_for_anomaly(session,company_id=record.company_id,anomaly_id=anomaly_id,
        erp_provider=provider,llm_client=llm,embedding_provider=embedder,language=language)

@router.get('/decisions',response_model=list[DecisionCard])
def decisions(company_id:str,request:Request,status:str|None=None,provider=Depends(get_provider),session:Session=Depends(get_db),limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0)):
    require_company(scope_for(request),company_id,provider)
    if status and status not in ('PROPOSED','APPROVED','REJECTED'): raise HTTPException(422,'Invalid status')
    return [to_card(r) for r in DecisionRepository(session).list_for_company(company_id,status,limit,offset,scope_for(request).tenant_id)]

@router.get('/decisions/{decision_id}',response_model=DecisionCard)
def decision(decision_id:str,request:Request,session:Session=Depends(get_db)):
    return to_card(require_record(scope_for(request),DecisionRepository(session).get(decision_id)))

@router.get('/decisions/{decision_id}/evidence', response_model=EvidencePackage)
def evidence(decision_id:str,request:Request,session:Session=Depends(get_db)):
    return require_record(scope_for(request),DecisionRepository(session).get(decision_id)).evidence_snapshot

@router.get('/decisions/{decision_id}/rag-context', response_model=list[RetrievedDecision])
def rag(decision_id:str,request:Request,session:Session=Depends(get_db)):
    return require_record(scope_for(request),DecisionRepository(session).get(decision_id)).rag_snapshot

@router.get('/decisions/{decision_id}/lifecycle')
def lifecycle(decision_id:str,request:Request,session:Session=Depends(get_db)):
    require_record(scope_for(request),DecisionRepository(session).get(decision_id))
    return [dict(from_status=e.from_status,to_status=e.to_status,actor=e.actor,note=e.note,occurred_at=e.occurred_at.isoformat()) for e in DecisionRepository(session).lifecycle(decision_id)]

@router.post('/decisions/{decision_id}/approve',response_model=DecisionCard)
def approve(decision_id:str,body:TransitionRequest,request:Request,session:Session=Depends(get_db),embedder=Depends(get_embedder)):
    require_record(scope_for(request),DecisionRepository(session).get(decision_id)); require_role(scope_for(request))
    return approve_decision(session,decision_id=decision_id,actor=scope_for(request).actor,note=body.note,embedding_provider=embedder)

@router.post('/decisions/{decision_id}/reject',response_model=DecisionCard)
def reject(decision_id:str,body:TransitionRequest,request:Request,session:Session=Depends(get_db)):
    require_record(scope_for(request),DecisionRepository(session).get(decision_id)); require_role(scope_for(request))
    return reject_decision(session,decision_id=decision_id,actor=scope_for(request).actor,reason=body.reason)

@router.post('/decisions/{decision_id}/retry-learning',response_model=DecisionCard)
def learning(decision_id:str,request:Request,session:Session=Depends(get_db),embedder=Depends(get_embedder)):
    record=require_record(scope_for(request),DecisionRepository(session).get(decision_id)); require_role(scope_for(request))
    retry_learning(session,record,embedder)
    return to_card(record)
