"""Read-only, tenant-scoped canonical/fact adapter; never writes to MOERPY."""
from datetime import date
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from app.data.models import Company,Store,Product,SalesFact,CostFact,InventoryFact,WasteReturnFact
from app.data.providers.base import ERPDataProvider

class PostgresERPProvider(ERPDataProvider):
    def __init__(self,database_url):
        url=make_url(database_url)
        if url.drivername in ('postgres','postgresql'): url=url.set(drivername='postgresql+psycopg')
        self._engine=create_engine(url,connect_args={'options':'-c default_transaction_read_only=on -c statement_timeout=15000'},pool_pre_ping=True)

    def query(self,sql,params=None):
        with self._engine.connect() as conn: return list(conn.execute(text(sql),params or {}).mappings())

    def list_companies(self):
        return [Company(str(r['id']),r['name'],'TRY',str(r['tenant_id'])) for r in self.query("SELECT id,name,tenant_id FROM public.companies WHERE status='active'")]

    def get_company(self,company_id):
        rows=self.query("SELECT id,name,tenant_id FROM public.companies WHERE id=CAST(:id AS uuid) AND status='active'",{'id':company_id})
        return Company(str(rows[0]['id']),rows[0]['name'],'TRY',str(rows[0]['tenant_id'])) if rows else None

    def scoped(self,table,company_id,condition='',**params):
        company=self.get_company(company_id)
        if not company: return []
        return self.query(f'SELECT * FROM public.{table} WHERE company_id=:company AND tenant_id=:tenant '+condition,
            dict(company=company_id,tenant=company.tenant_id,**params))

    def lineage(self,r):
        return dict(tenant_id=str(r['tenant_id']),import_batch_id=r['import_batch_id'],source_system=r['source_system'],variant_id=r['product_variant_id'])

    def list_stores(self,company_id):
        return [Store(r['canonical_store_id'],company_id,r['canonical_store_code'],r['canonical_store_name'],r['region'] or '',r['city'] or '') for r in self.scoped('canonical_stores',company_id)]

    def list_products(self,company_id):
        return [Product(r['canonical_product_id'],company_id,r['canonical_product_id'],r['canonical_product_name'],r.get('category_family') or 'Uncategorized',r['unit_of_measure']) for r in self.scoped('canonical_products',company_id)]

    def get_sales_facts(self,company_id,period):
        return [SalesFact(id=r['sales_fact_id'],company_id=company_id,store_id=r['canonical_store_id'],product_id=r['canonical_product_id'],period=period,
            sales_date=r['sales_date'],quantity_sold=float(r['quantity_sold']),revenue=float(r['revenue']),discount=float(r['discount'] or 0),
            unit_cost=float(r['unit_cost']) if r['unit_cost'] is not None else None,**self.lineage(r))
            for r in self.scoped('sales_facts',company_id,'AND sales_date BETWEEN :start AND :end ORDER BY sales_date,sales_fact_id',start=period.start,end=period.end)]

    def get_cost_facts(self,company_id,period):
        return [CostFact(id=r['cost_fact_id'],company_id=company_id,product_id=r['canonical_product_id'],period=period,
            standard_unit_cost=float(r['unit_cost']),currency=r['currency'],supplier=r['supplier'] or '',store_id=r['canonical_store_id'],
            effective_date=r['effective_date'],is_budget=False,**self.lineage(r))
            for r in self.scoped('cost_facts',company_id,'AND effective_date<=:end ORDER BY effective_date,cost_fact_id',end=period.end)]

    def get_inventory_facts(self,company_id,as_of):
        rows=self.scoped('inventory_facts',company_id,'AND inventory_date<=:as_of ORDER BY inventory_date,inventory_fact_id',as_of=as_of)
        # Keep all lot/variant rows at each location/product's latest snapshot.
        latest={}
        for r in rows: latest[(r['canonical_store_id'],r['canonical_product_id'],r['product_variant_id'])]=r['inventory_date']
        return [InventoryFact(id=r['inventory_fact_id'],company_id=company_id,store_id=r['canonical_store_id'],product_id=r['canonical_product_id'],
            snapshot_date=r['inventory_date'],quantity=float(r['quantity']),unit_cost=float(r['unit_cost']) if r['unit_cost'] is not None else None,**self.lineage(r))
            for r in rows if r['inventory_date']==latest[(r['canonical_store_id'],r['canonical_product_id'],r['product_variant_id'])]]

    def get_waste_return_facts(self,company_id,period):
        return [WasteReturnFact(id=r['waste_return_fact_id'],company_id=company_id,store_id=r['canonical_store_id'],product_id=r['canonical_product_id'],
            event_date=r['event_date'],event_type=r['event_type'],quantity=float(r['quantity']),reason=r['reason'] or '',**self.lineage(r))
            for r in self.scoped('waste_return_facts',company_id,'AND event_date BETWEEN :start AND :end ORDER BY event_date,waste_return_fact_id',start=period.start,end=period.end)]
