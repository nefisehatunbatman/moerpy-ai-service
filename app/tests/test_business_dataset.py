"""Integration tests against the verified main dataset, independent of fixture tests."""
from pathlib import Path
from datetime import date
from decimal import Decimal
import pytest
from app.data.models import Period
from app.data.providers.business_provider import BusinessERPProvider
from app.kpi.engine import compute_kpis

@pytest.fixture(scope='module')
def business():
    path=Path(__file__).resolve().parents[2]/'data/business_24m.db'
    if not path.exists(): pytest.skip('Main business dataset must be built separately')
    return BusinessERPProvider(path)

def test_main_corpus_size_and_oracle_separation(business):
    assert business.metadata['dataset_id']=='c40c0f076d3f510c83c57553'
    assert business.metadata['imported_rows']==1050029
    assert business.metadata['source_rows']==1577755
    with business.connection() as conn:
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any('private' in t or 'scenario' in t or 'oracle' in t for t in tables)
    assert business.metadata['private_oracle_used'] is False

@pytest.mark.parametrize('year,month',[(2024+(8+n)//12,(8+n)%12+1) for n in range(24)])
def test_monthly_revenue_and_cogs_reconciliation(business,year,month):
    from datetime import timedelta
    end=date(year+month//12,month%12+1,1)-timedelta(days=1)
    company=business.list_companies()[0]
    period=Period(date(year,month,1),end)
    kpis=compute_kpis(business,company.id,period)
    by_name={k.metric:k for k in kpis if k.entity_type=='company'}
    headers=business.rows("SELECT net_amount_try FROM sales_invoices WHERE company_id=? AND invoice_date BETWEEN ? AND ? AND status='posted' AND substr(available_at,1,10)<=?",
        (company.id,str(period.start),str(end),str(end)))
    expected=sum((Decimal(r['net_amount_try']) for r in headers),Decimal(0))
    assert by_name['revenue'].value==float(expected.quantize(Decimal('.01')))
    lines=business.rows('''SELECT l.cogs_try FROM sales_invoice_lines l JOIN sales_invoices i ON l.invoice_id=i.invoice_id AND l.company_id=i.company_id AND l.tenant_id=i.tenant_id
        WHERE i.company_id=? AND i.invoice_date BETWEEN ? AND ? AND i.status='posted'
        AND substr(i.available_at,1,10)<=? AND substr(l.available_at,1,10)<=? AND substr(l.cost_available_at,1,10)<=?''',
        (company.id,str(period.start),str(end),str(end),str(end),str(end)))
    expected_cogs=sum((Decimal(r['cogs_try']) for r in lines),Decimal(0))
    if by_name['cogs'].value is not None:
        assert by_name['cogs'].value==float(expected_cogs.quantize(Decimal('.01')))
    assert all(k.tenant_id==company.tenant_id for k in kpis)

def test_stock_and_waste_are_not_future_information(business):
    company=business.list_companies()[0]
    period=Period(date(2026,8,1),date(2026,8,31))
    inventory=business.get_inventory_facts(company.id,period.end)
    assert inventory and all(f.snapshot_date<=period.end for f in inventory)
    waste=business.get_waste_return_facts(company.id,period)
    assert waste and all(period.start<=f.event_date<=period.end for f in waste)
    assert all(f.reason in ('waste','expiry_writeoff') for f in waste)
    assert not business.get_sales_facts('foreign-company',period)
