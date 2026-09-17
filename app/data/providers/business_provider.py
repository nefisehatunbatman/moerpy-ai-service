"""Read-only indexed access to the full 24-month business corpus; as-of visibility enforced."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from app.data.models import Company,Store,Product,SalesFact,CostFact,InventoryFact,WasteReturnFact,Period
from app.data.providers.base import ERPDataProvider
from app.core.errors import InvalidPeriodError

def available_at(value, as_of):
    """An empty availability timestamp is unknown, never evidence of availability."""
    return bool(value) and value[:10] <= str(as_of)

class BusinessERPProvider(ERPDataProvider):
    def __init__(self,path):
        self.path=Path(path).resolve()
        with self.connection() as conn:
            self.metadata=json.loads(conn.execute('SELECT document FROM dataset_metadata').fetchone()[0])

    @contextmanager
    def connection(self):
        conn=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)
        conn.row_factory=sqlite3.Row
        try: yield conn
        finally: conn.close()

    def rows(self,sql,params=()):
        with self.connection() as conn: return list(conn.execute(sql,params))

    def lineage(self,row):
        return dict(tenant_id=row['tenant_id'],import_batch_id=self.metadata['dataset_id'],source_system='business_24m')

    def validate_period(self, period):
        bounds = self.metadata.get('date_range')
        if bounds and (str(period.start) < bounds['start'] or str(period.end) > bounds['end']):
            raise InvalidPeriodError('Requested period exceeds the verified business dataset coverage')

    def list_companies(self):
        return [Company(r['company_id'],r['legal_name'],r['base_currency'],r['tenant_id']) for r in self.rows('SELECT * FROM companies')]

    def get_company(self,company_id):
        return next((c for c in self.list_companies() if c.id==company_id),None)

    def list_stores(self,company_id):
        return [Store(r['location_id'],company_id,r['location_code'],r['name'],r['region'],r['city']) for r in self.rows('SELECT * FROM locations WHERE company_id=?',(company_id,))]

    def list_products(self,company_id):
        return [Product(r['product_id'],company_id,r['sku'],r['name'],r['category'],r['base_uom']) for r in self.rows('SELECT * FROM master_products WHERE company_id=?',(company_id,))]

    def get_sales_facts(self,company_id,period):
        self.validate_period(period)
        rows=self.rows('''SELECT l.*, i.selling_location_id, i.invoice_date FROM sales_invoices i
            JOIN sales_invoice_lines l ON l.invoice_id=i.invoice_id AND l.company_id=i.company_id AND l.tenant_id=i.tenant_id
            WHERE i.company_id=? AND i.invoice_date BETWEEN ? AND ? AND i.status='posted'
            AND i.available_at<>'' AND l.available_at<>''
            AND substr(i.available_at,1,10)<=? AND substr(l.available_at,1,10)<=?''',
            (company_id,str(period.start),str(period.end),str(period.end),str(period.end)))
        return [SalesFact(id=r['invoice_line_id'],company_id=company_id,store_id=r['selling_location_id'],product_id=r['product_id'],
            period=period,quantity_sold=float(r['quantity_kg']),revenue=float(r['net_amount_try']),discount=float(r['discount_amount_try']),
            unit_cost=None,sales_date=date.fromisoformat(r['invoice_date']),
            cogs_amount=float(r['cogs_try']) if available_at(r['cost_available_at'],period.end) and r['cogs_try'] not in (None,'') else None,
            cost_basis_known=available_at(r['cost_available_at'],period.end) and r['cogs_try'] not in (None,''),
            **self.lineage(r)) for r in rows]

    def get_cost_facts(self,company_id,period):
        self.validate_period(period)
        rows=self.rows('''SELECT * FROM cost_history WHERE company_id=? AND effective_from<=? AND effective_to>=?
            AND source_available_at<>'' AND substr(source_available_at,1,10)<=?''',(company_id,str(period.end),str(period.start),str(period.end)))
        return [CostFact(id=r['cost_history_id'],company_id=company_id,product_id=r['product_id'],period=period,
            standard_unit_cost=float(r['total_unit_cost_try']),currency='TRY',supplier=r['supplier_id'],
            effective_date=date.fromisoformat(r['effective_from']),effective_to=date.fromisoformat(r['effective_to']),is_budget=False,
            **self.lineage(r)) for r in rows]

    def get_inventory_facts(self,company_id,as_of):
        # Dataset contains complete daily snapshots. Do not resurrect products omitted from the latest snapshot.
        rows=self.rows('''SELECT * FROM inventory_snapshots WHERE company_id=? AND snapshot_date=(
            SELECT MAX(snapshot_date) FROM inventory_snapshots WHERE company_id=? AND snapshot_date<=?)
            AND source_max_available_at<>'' AND substr(source_max_available_at,1,10)<=?''',(company_id,company_id,str(as_of),str(as_of)))
        return [InventoryFact(id=f"{r['snapshot_date']}:{r['location_id']}:{r['product_id']}",company_id=company_id,
            store_id=r['location_id'],product_id=r['product_id'],snapshot_date=date.fromisoformat(r['snapshot_date']),
            quantity=float(r['quantity_kg']),unit_cost=None,
            inventory_value=float(r['inventory_value_try']) if available_at(r['inventory_value_available_at'],as_of) and r['inventory_value_try'] not in (None,'') else None,
            **self.lineage(r)) for r in rows]

    def get_waste_return_facts(self,company_id,period):
        self.validate_period(period)
        rows=self.rows('''SELECT * FROM inventory_movements WHERE company_id=? AND event_date BETWEEN ? AND ?
            AND movement_type IN ('waste','expiry_writeoff','spoilage','waste_writeoff') AND available_at<>'' AND substr(available_at,1,10)<=?''',
            (company_id,str(period.start),str(period.end),str(period.end)))
        return [WasteReturnFact(id=r['movement_id'],company_id=company_id,store_id=r['location_id'],product_id=r['product_id'],
            event_date=date.fromisoformat(r['event_date']),event_type='waste',quantity=abs(float(r['quantity_kg'])),reason=r['movement_type'],
            cost_amount=abs(float(r['total_cost_try'])) if available_at(r['cost_available_at'],period.end) and r['total_cost_try'] not in (None,'') else None,
            cost_basis_known=available_at(r['cost_available_at'],period.end) and r['total_cost_try'] not in (None,''),
            **self.lineage(r)) for r in rows]
