"""Review regressions: independent numeric expectations and failure/concurrency paths."""
from datetime import date
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.data.models import Period,SalesFact,InventoryFact,Store,Company,Product,CostFact
from app.data.providers.fake_provider import FakeERPDataProvider
from app.kpi.engine import compute_kpis
from app.anomaly.detector import detect_anomalies
from app.anomaly.repository import AnomalyRepository
from app.thresholds.repository import ThresholdRepository
from app.thresholds.defaults import get_seed_thresholds
from app.decisions.service import generate_decision_for_anomaly,approve_decision,reject_decision,retry_learning,InvalidDecisionTransitionError
from app.decisions.repository import DecisionRepository
from app.llm.client import FakeLLMClient
from app.rag.embeddings import LocalHashEmbedding
from app.rag.knowledge_base import KnowledgeBaseRepository
from app.db.base import Base

FEB=Period(date(2026,2,1),date(2026,2,28))

class SmallProvider(FakeERPDataProvider):
    def __init__(self,sales=None,inventory=None,costs=None):
        self.sales=sales or [];self.inventory=inventory or [];self.costs=costs or []
    def get_company(self,c): return Company('C','Company','TRY','fixture-tenant') if c=='C' else None
    def list_stores(self,c): return [Store('S','C','S','Store','','')]
    def list_products(self,c): return [Product('P','C','P','Product','Category','unit')]
    def get_sales_facts(self,c,p): return self.sales
    def get_cost_facts(self,c,p): return self.costs
    def get_inventory_facts(self,c,p): return self.inventory
    def get_waste_return_facts(self,c,p): return []

def sale(id,cost,day=1):
    return SalesFact(id,'C','S','P',FEB,1,100,0,cost,sales_date=date(2026,2,day),tenant_id='fixture-tenant')

def company_metric(rows,metric): return next(r for r in rows if r.metric==metric and r.entity_type=='company')

def test_line_costs_do_not_overwrite_each_other():
    for rows in ([sale('1',10),sale('2',20)],[sale('2',20),sale('1',10)]):
        assert company_metric(compute_kpis(SmallProvider(rows),'C',FEB),'cogs').value==30

def test_effective_cost_before_period_and_change_during_period():
    costs=[CostFact('old','C','P',FEB,10,'TRY','supplier',tenant_id='fixture-tenant',effective_date=date(2026,1,1)),
           CostFact('new','C','P',FEB,20,'TRY','supplier',tenant_id='fixture-tenant',effective_date=date(2026,2,15))]
    result=compute_kpis(SmallProvider([sale('1',None,1),sale('2',None,20)],costs=costs),'C',FEB)
    assert company_metric(result,'cogs').value==30
    assert 'CostFact:old' in company_metric(result,'cogs').source_ids
    assert 'CostFact:new' in company_metric(result,'cogs').source_ids

def test_run_fingerprint_is_order_independent_and_tracks_source_changes(db_session):
    provider,kpis,_,_=prepare(db_session)
    thresholds=ThresholdRepository(db_session).list_for_company('COMP-001')
    first=detect_anomalies('COMP-001',FEB,kpis,thresholds)
    second=detect_anomalies('COMP-001',FEB,list(reversed(kpis)),list(reversed(thresholds)))
    assert {a.id for a in first}=={a.id for a in second}
    changed=[k.model_copy(update={'source_digest':'changed-source'}) for k in kpis]
    third=detect_anomalies('COMP-001',FEB,changed,thresholds)
    assert {a.id for a in first}.isdisjoint({a.id for a in third})

def test_missing_cost_is_not_free_and_zero_sales_is_not_zero_dio():
    missing=company_metric(compute_kpis(SmallProvider([sale('1',None)]),'C',FEB),'gross_margin_pct')
    assert missing.value is None and missing.status=='insufficient_data'
    inventory=[InventoryFact('I','C','S','P',FEB.end,100,10,tenant_id='fixture-tenant')]
    result=compute_kpis(SmallProvider(inventory=inventory),'C',FEB)
    assert next(r for r in result if r.metric=='inventory_value').value==1000
    assert next(r for r in result if r.metric=='days_inventory_outstanding').value is None

def test_future_stock_cost_cannot_price_earlier_sale():
    inventory=[InventoryFact('I','C','S','P',FEB.end,100,10,tenant_id='fixture-tenant')]
    result=compute_kpis(SmallProvider([sale('1',None,1)],inventory),'C',FEB)
    assert company_metric(result,'cogs').value is None

def test_unavailable_actual_cost_cannot_fall_back_to_an_estimate():
    costs=[CostFact('old','C','P',FEB,10,'TRY','supplier',tenant_id='fixture-tenant')]
    row=replace(sale('1',None),cost_basis_known=False)
    assert company_metric(compute_kpis(SmallProvider([row],costs=costs),'C',FEB),'cogs').value is None

def test_nan_and_negative_source_values_are_rejected():
    for v in (float('nan'),float('inf'),-1):
        with pytest.raises(ValueError): compute_kpis(SmallProvider([sale('1',v)]),'C',FEB)

def test_partial_fixture_period_does_not_include_monthly_total():
    p=FakeERPDataProvider()
    with pytest.raises(ValueError, match='Partial fixture period'):
        p.get_sales_facts('COMP-001',Period(date(2026,2,1),date(2026,2,1)))

def prepare(session):
    provider=FakeERPDataProvider(); repo=ThresholdRepository(session)
    repo.seed_if_empty('COMP-001',get_seed_thresholds('COMP-001'))
    kpis=compute_kpis(provider,'COMP-001',FEB)
    anomalies=detect_anomalies('COMP-001',FEB,kpis,repo.list_for_company('COMP-001'))
    AnomalyRepository(session).save_all(anomalies)
    a=next(a for a in anomalies if a.metric=='working_capital_in_inventory_pct')
    return provider,kpis,anomalies,a

def generate(session,provider,a):
    return generate_decision_for_anomaly(session,company_id='COMP-001',anomaly_id=a.id,erp_provider=provider,llm_client=FakeLLMClient(),embedding_provider=LocalHashEmbedding())

def test_snapshot_survives_provider_changes_and_reruns_supersede(db_session):
    provider,kpis,old,a=prepare(db_session)
    provider._sales_facts=[]
    card=generate(db_session,provider,a)
    assert card.observed_impact['value']==492000
    current=[k.model_copy(update={'value':k.value+1}) if k.value is not None else k for k in kpis]
    new=detect_anomalies('COMP-001',FEB,current,ThresholdRepository(db_session).list_for_company('COMP-001'))
    assert {a.id for a in new}.isdisjoint({a.id for a in old})
    AnomalyRepository(db_session).save_all(new)
    assert not AnomalyRepository(db_session).get(a.id).active
    with pytest.raises(InvalidDecisionTransitionError): generate(db_session,provider,a)
    AnomalyRepository(db_session).save_all([],'COMP-001',FEB)
    assert AnomalyRepository(db_session).list_for_company('COMP-001')==[]

def test_cost_variance_companion_stays_in_evidence(db_session):
    provider,kpis,anomalies,_=prepare(db_session)
    a=next(a for a in anomalies if a.metric=='unit_cost_variance_pct')
    card=generate(db_session,provider,a)
    assert 'unit_cost_variance_try' in [s.metric for s in card.signals]

def test_learning_failure_has_explicit_retry_and_receipt(db_session):
    provider,_,_,a=prepare(db_session); card=generate(db_session,provider,a)
    class Broken(LocalHashEmbedding):
        def embed(self,text): raise RuntimeError('offline failure')
    approved=approve_decision(db_session,decision_id=card.id,actor='cfo',note=None,embedding_provider=Broken())
    assert approved.status=='APPROVED' and approved.learning_status=='failed'
    record=DecisionRepository(db_session).get(card.id)
    retry_learning(db_session,record,LocalHashEmbedding())
    assert record.learning_status=='completed'
    kb=KnowledgeBaseRepository(db_session,LocalHashEmbedding())
    counts={e.id:e.approval_count for e in kb.list_all()}
    record.learning_status='failed';db_session.commit() # retry after receipt committed but completion response lost
    retry_learning(db_session,record,LocalHashEmbedding())
    assert {e.id:e.approval_count for e in kb.list_all()}==counts

def test_embedding_switch_requires_atomic_reindex(db_session):
    kb=KnowledgeBaseRepository(db_session,LocalHashEmbedding());kb.seed_if_empty()
    class Different(LocalHashEmbedding):
        @property
        def identity(self): return 'different-model-same-dimension'
    switched=KnowledgeBaseRepository(db_session,Different())
    with pytest.raises(ValueError,match='index version'): switched.search('margin','COMP-001')
    switched.reindex()
    assert all(e.embedding_model==Different().identity for e in switched.list_all())
    switched.search('margin','COMP-001')

def test_concurrent_approve_reject_only_one_wins(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'concurrency.db'),connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        provider,_,_,a=prepare(session);card=generate(session,provider,a)
    import threading
    barrier=threading.Barrier(2)
    def transition(kind):
        with Session(engine) as session:
            record=DecisionRepository(session).get(card.id)
            barrier.wait()
            try:
                DecisionRepository(session).transition(record,kind,'reviewer')
                return 'won'
            except InvalidDecisionTransitionError: return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(transition,['APPROVED','REJECTED']))
    assert sorted(results)==['conflict','won']
    with Session(engine) as session:
        assert len(DecisionRepository(session).lifecycle(card.id))==3
    engine.dispose()

@pytest.mark.parametrize('claim',['999999 gün','Yüzde otuz yedi tasarruf','Stok değeri %492000','492,000 TRY tasarruf','iki ayda kazanım'])
def test_unsupported_numeric_claims_rejected(db_session,claim):
    from app.evidence.models import EvidencePackage
    from app.llm.schemas import LLMDecisionOutput
    from app.llm.decision_generator import verify_number_grounding,NumberGroundingError
    provider,_,_,a=prepare(db_session);card=generate(db_session,provider,a)
    evidence=EvidencePackage.model_validate(DecisionRepository(db_session).get(card.id).evidence_snapshot)
    output=LLMDecisionOutput(title='Test',summary=claim,problem_signal='Test',recommended_decision='Test',reasoning=['Test'],expected_impact=[],decision_type='CASH_FLOW')
    with pytest.raises(NumberGroundingError): verify_number_grounding(output,evidence)

