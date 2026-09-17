"""Offline full-corpus reconciliation and 24-month decision generation."""
import os
import sys
import json
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.update(AI_SERVICE_DATABASE_URL='sqlite://',ERP_PROVIDER='business',BUSINESS_DATASET_DB=str(ROOT/'data/business_24m.db'),
    LLM_API_KEY='',EMBEDDING_API_KEY='',LLM_MODE='offline',EMBEDDING_MODE='local',ENVIRONMENT='test')
from app.data.providers.business_provider import BusinessERPProvider
from app.kpi.engine import compute_kpis
from app.data.models import Period
from app.db.base import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.thresholds.repository import ThresholdRepository
from app.thresholds.defaults import get_seed_thresholds
from app.anomaly.detector import detect_anomalies
from app.anomaly.repository import AnomalyRepository
from app.decisions.service import generate_decision_for_anomaly
from app.llm.client import FakeLLMClient
from app.rag.embeddings import LocalHashEmbedding
from app.decisions import models
from app.rag import models

provider=BusinessERPProvider(ROOT/'data/business_24m.db')
company=provider.list_companies()[0]
engine=create_engine('sqlite://')
Base.metadata.create_all(engine)
out={'dataset':provider.metadata,'months':[],'private_oracle_used':False,'live_model_used':False}
start=time.perf_counter()
with provider.connection() as conn:
    out['movement_types']=[list(r) for r in conn.execute('SELECT movement_type,count(*) FROM inventory_movements GROUP BY movement_type')]
with Session(engine) as session:
    repo=ThresholdRepository(session,company.tenant_id); repo.seed_if_empty(company.id,get_seed_thresholds(company.id))
    for n in range(24):
        year=2024+(8+n)//12; month=(8+n)%12+1
        following=date(year+month//12,month%12+1,1)
        from datetime import timedelta
        period=Period(date(year,month,1),following-timedelta(days=1))
        t=time.perf_counter(); kpis=compute_kpis(provider,company.id,period)
        company_kpis={k.metric:k.value for k in kpis if k.entity_type=='company'}
        # Independently reconcile against posted invoice header amounts, not the KPI code.
        headers=provider.rows("SELECT net_amount_try FROM sales_invoices WHERE company_id=? AND invoice_date BETWEEN ? AND ? AND status='posted' AND substr(available_at,1,10)<=?",
            (company.id,str(period.start),str(period.end),str(period.end)))
        expected=float(sum((Decimal(r['net_amount_try']) for r in headers),Decimal(0)))
        if company_kpis['revenue']!=round(expected,2):
            raise AssertionError(f'Revenue reconciliation failed: {period} {company_kpis["revenue"]} != {expected}')
        anomalies=detect_anomalies(company.id,period,kpis,repo.list_for_company(company.id))
        AnomalyRepository(session).save_all(anomalies,company.id,period,company.tenant_id)
        cards=[]
        for anomaly in anomalies:
            card=generate_decision_for_anomaly(session,company_id=company.id,anomaly_id=anomaly.id,
                erp_provider=provider,llm_client=FakeLLMClient(),embedding_provider=LocalHashEmbedding())
            assert all(i.type=='qualitative' and i.value is None for i in card.expected_impact)
            assert card.tenant_id==company.tenant_id and card.company_id==company.id
            cards.append(card.model_dump())
        out['months'].append({'start':str(period.start),'end':str(period.end),'kpis':len(kpis),
            'insufficient_metrics':sum(k.value is None for k in kpis),'anomalies':len(anomalies),'decisions':len(cards),
            'company_kpis':company_kpis,'revenue_matches_invoice_headers':True,'elapsed_seconds':round(time.perf_counter()-t,3)})
        if n==23: out['sample_decisions']=cards[:3]
        print(f'{period.start}: {len(kpis)} KPIs, {len(cards)} decisions, revenue reconciled',flush=True)
out['elapsed_seconds']=round(time.perf_counter()-start,3)
out['total_decisions']=sum(m['decisions'] for m in out['months'])
(ROOT/'data/business_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(f"Validated 24 months in {out['elapsed_seconds']} seconds; {out['total_decisions']} decisions")
