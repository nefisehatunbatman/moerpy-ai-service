"""Real PostgreSQL contract checks in the disposable compose.test.yaml database."""
import os
from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from app.data.models import Period
from app.data.providers.postgres_v2 import PostgresERPProvider
from app.kpi.engine import compute_kpis
from app.db.base import Base

COMPANY = '22222222-2222-4222-8222-222222222222'
TENANT = '11111111-1111-4111-8111-111111111111'


@pytest.fixture(scope='module')
def postgres():
    url = os.environ.get('TEST_POSTGRES_URL')
    if not url:
        pytest.skip('Use the postgres profile in compose.test.yaml')
    parsed = make_url(url)
    if parsed.database != 'ai_service_test' or parsed.host != 'postgres':
        pytest.fail('This test only writes to the disposable compose postgres/ai_service_test database')
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE companies (id uuid PRIMARY KEY, tenant_id uuid, name text, status text)'))
        conn.execute(text("INSERT INTO companies VALUES (:company,:tenant,'Test','active')"), dict(company=COMPANY,tenant=TENANT))
        common = 'company_id uuid, tenant_id uuid, import_batch_id text, source_system text, product_variant_id text'
        tables = {
            'canonical_stores': f'{common}, canonical_store_id text, canonical_store_code text, canonical_store_name text, region text, city text',
            'canonical_products': f'{common}, canonical_product_id text, canonical_product_name text, category_family text, unit_of_measure text',
            'sales_facts': f'{common}, sales_fact_id text, canonical_store_id text, canonical_product_id text, sales_date date, quantity_sold numeric, revenue numeric, discount numeric, unit_cost numeric',
            'cost_facts': f'{common}, cost_fact_id text, canonical_store_id text, canonical_product_id text, effective_date date, unit_cost numeric, currency text, supplier text',
            'inventory_facts': f'{common}, inventory_fact_id text, canonical_store_id text, canonical_product_id text, inventory_date date, quantity numeric, unit_cost numeric',
            'waste_return_facts': f'{common}, waste_return_fact_id text, canonical_store_id text, canonical_product_id text, event_date date, event_type text, quantity numeric, reason text',
        }
        for table, columns in tables.items():
            conn.execute(text(f'CREATE TABLE {table} ({columns})'))
        params = dict(company=COMPANY,tenant=TENANT)
        conn.execute(text("INSERT INTO canonical_stores(company_id,tenant_id,canonical_store_id,canonical_store_code,canonical_store_name) VALUES(:company,:tenant,'S','S','Store')"),params)
        conn.execute(text("INSERT INTO canonical_products(company_id,tenant_id,canonical_product_id,canonical_product_name,unit_of_measure) VALUES(:company,:tenant,'P','Product','unit')"),params)
        conn.execute(text("INSERT INTO sales_facts(company_id,tenant_id,import_batch_id,source_system,sales_fact_id,canonical_store_id,canonical_product_id,sales_date,quantity_sold,revenue) VALUES(:company,:tenant,'B','test','sale','S','P','2026-02-01',2,100)"),params)
        conn.execute(text("INSERT INTO cost_facts(company_id,tenant_id,import_batch_id,source_system,cost_fact_id,canonical_store_id,canonical_product_id,effective_date,unit_cost,currency) VALUES(:company,:tenant,'B','test','cost','S','P','2026-01-01',10,'TRY')"),params)
        conn.execute(text("INSERT INTO inventory_facts(company_id,tenant_id,import_batch_id,source_system,inventory_fact_id,canonical_store_id,canonical_product_id,inventory_date,quantity,unit_cost) VALUES(:company,:tenant,'B','test','stock','S','P','2026-02-28',5,10)"),params)
    yield engine
    engine.dispose()


def test_real_postgres_adapter_and_kpi_contract(postgres):
    provider = PostgresERPProvider(os.environ['TEST_POSTGRES_URL'])
    try:
        rows = compute_kpis(provider, COMPANY, Period(date(2026,2,1),date(2026,2,28)))
        company = {r.metric: r.value for r in rows if r.entity_type == 'company'}
        assert company['revenue'] == 100 and company['cogs'] == 20
        assert company['gross_margin_pct'] == 80
        assert all(r.tenant_id == TENANT for r in rows)
        assert not any(r.metric == 'unit_cost_variance_pct' for r in rows)
    finally:
        provider._engine.dispose()


def test_erp_adapter_connection_is_read_only(postgres):
    provider = PostgresERPProvider(os.environ['TEST_POSTGRES_URL'])
    try:
        with pytest.raises(DBAPIError):
            provider.query("UPDATE companies SET name='must-not-write'")
    finally:
        provider._engine.dispose()


def test_postgres_ai_state_and_learning_lifecycle(postgres):
    from app.tests.test_regressions import prepare, generate
    from app.decisions.service import approve_decision
    from app.rag.embeddings import LocalHashEmbedding
    Base.metadata.create_all(postgres)
    with Session(postgres) as session:
        provider, _, _, anomaly = prepare(session)
        card = generate(session, provider, anomaly)
        approved = approve_decision(session, decision_id=card.id, actor='test-finance', note=None, embedding_provider=LocalHashEmbedding())
        assert approved.status == 'APPROVED' and approved.learning_status == 'completed'
