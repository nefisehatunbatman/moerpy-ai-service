"""Point-in-time calculations with explicit missing-data and source lineage."""
from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal
import hashlib
import math
import json
import calendar
from app.data.models import Period, SalesFact, CostFact
from app.data.providers.base import ERPDataProvider
from app.kpi.models import KpiResult, PeriodOut
from app.core.config import get_settings
from app.core.errors import InvalidSourceDataError, CompanyNotFoundError

def total(values):
    return float(sum((Decimal(str(v)) for v in values), Decimal(0)))

def cost_for(fact, costs, *, budget=False):
    day = getattr(fact, 'sales_date', None) or getattr(fact, 'event_date', None) or fact.period.end
    eligible = [c for c in costs if c.is_budget == budget and c.product_id == fact.product_id and c.store_id in (None, fact.store_id)
                and c.variant_id in (None, fact.variant_id) and (c.effective_date or c.period.start) <= day
                and (c.effective_to is None or day <= c.effective_to)]
    if not eligible:
        return None
    priority = lambda c: (c.store_id is not None, c.variant_id is not None, c.effective_date or c.period.start)
    best = max(map(priority, eligible))
    candidates = [c for c in eligible if priority(c) == best]
    if len({c.standard_unit_cost for c in candidates}) != 1:
        raise InvalidSourceDataError('Conflicting costs with the same scope and effective date')
    return min(candidates, key=lambda c: c.id)

def compute_kpis(provider: ERPDataProvider, company_id: str, period: Period) -> list[KpiResult]:
    company = provider.get_company(company_id)
    if company is None:
        raise CompanyNotFoundError('Company not found')
    if company.currency != 'TRY':
        raise InvalidSourceDataError('Only TRY normalized facts are supported')
    stores = {s.id: s.code for s in provider.list_stores(company_id)}
    products = {p.id: p.code for p in provider.list_products(company_id)}
    sales = provider.get_sales_facts(company_id, period)
    costs = provider.get_cost_facts(company_id, period)
    inventory = provider.get_inventory_facts(company_id, period.end)
    waste = provider.get_waste_return_facts(company_id, period)
    seen = set()
    for f in [*sales, *costs, *inventory, *waste]:
        key = (type(f).__name__, f.id)
        if key in seen:
            raise InvalidSourceDataError(f'Duplicate {key[0]} source ID')
        seen.add(key)
        required = (('quantity_sold', 'revenue', 'discount') if isinstance(f, SalesFact) else
                    ('standard_unit_cost',) if isinstance(f, CostFact) else ('quantity',))
        if any(getattr(f, name, None) is None for name in required):
            raise InvalidSourceDataError('Required source field is missing')
        if f.company_id != company_id or f.tenant_id != company.tenant_id:
            raise InvalidSourceDataError('Provider returned facts outside company/tenant scope')
        if f.product_id not in products or (getattr(f, 'store_id', None) is not None and f.store_id not in stores):
            raise InvalidSourceDataError('Unresolved canonical fact reference')
        for name in ('quantity_sold','quantity','unit_cost','revenue','discount','standard_unit_cost','cogs_amount','inventory_value','cost_amount'):
            value=getattr(f,name,None)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(value) or value<0):
                raise InvalidSourceDataError(f'Invalid normalized {name}; quarantine the source row')
    for f in sales:
        if f.sales_date is not None:
            valid = period.start <= f.sales_date <= period.end
        else:
            valid = period.start <= f.period.start <= f.period.end <= period.end
        if not valid:
            raise InvalidSourceDataError('Sales outside the requested period')
    if any(f.snapshot_date > period.end for f in inventory):
        raise InvalidSourceDataError('Inventory snapshot is in the future of the requested period')
    if any(not period.start <= f.event_date <= period.end for f in waste):
        raise InvalidSourceDataError('Waste outside the requested period')
    if any(c.currency != 'TRY' for c in costs):
        raise InvalidSourceDataError('Unconverted currencies in cost facts')
    result = []
    fingerprints={}
    cost_index=defaultdict(list)
    for c in costs: cost_index[c.product_id].append(c)
    cost_cache={}
    def resolve(f, budget=False):
        key=(f.store_id,f.product_id,f.variant_id,getattr(f,'sales_date',None) or getattr(f,'event_date',None) or f.period.end,budget)
        if key not in cost_cache: cost_cache[key]=cost_for(f,cost_index[f.product_id],budget=budget)
        return cost_cache[key]
    def emit(kind, entity, metric, value, unit, facts, formula, issues=(), coverage=1.0, snapshot=None):
        if value is not None and not math.isfinite(value):
            raise InvalidSourceDataError('Non-finite calculated KPI')
        references={type(f).__name__+':'+f.id:f for f in facts}
        ids=sorted(references)
        for ref,fact in references.items():
            if ref not in fingerprints:
                fingerprints[ref]=hashlib.sha256(json.dumps(asdict(fact),sort_keys=True,default=str).encode()).hexdigest()
        result.append(KpiResult.now(company_id=company_id, tenant_id=company.tenant_id, entity_type=kind, entity_id=entity,
            metric=metric, value=round(value,2) if value is not None else None, unit=unit, period=PeriodOut.from_period(period),
            source=', '.join(sorted({f.source_system for f in facts})) or 'no_data', formula=formula,
            status='insufficient_data' if value is None else ('degraded' if issues else 'ok'), issues=list(issues), coverage=coverage,
            source_ids=ids[:20], source_count=len(ids), source_digest=hashlib.sha256('|'.join(fingerprints[ref] for ref in ids).encode()).hexdigest(),
            import_batch_ids=sorted({f.import_batch_id for f in facts}), snapshot_date=snapshot))
    by_store = defaultdict(list)
    for f in sales:
        if f.store_id not in stores or f.product_id not in products:
            raise InvalidSourceDataError('Unresolved canonical sales reference')
        by_store[f.store_id].append(f)
    inventory_by_pair = defaultdict(list)
    for f in inventory:
        inventory_by_pair[(f.store_id,f.product_id,f.variant_id)].append(f)
    actual = {}
    dependencies={}
    for f in sales:
        if not f.cost_basis_known: continue
        baseline = resolve(f)
        if f.cogs_amount is not None:
            actual[f.id] = f.cogs_amount
        elif f.unit_cost is not None:
            actual[f.id] = f.quantity_sold*f.unit_cost
        elif baseline:
            actual[f.id] = f.quantity_sold*baseline.standard_unit_cost
            dependencies[f.id]=[baseline]
        else:
            day = f.sales_date or f.period.end
            candidates = [s for s in inventory_by_pair.get((f.store_id,f.product_id,f.variant_id), [])
                          if 0 <= (day-s.snapshot_date).days <= get_settings().inventory_max_age_days]
            if candidates:
                latest = max(s.snapshot_date for s in candidates)
                candidates = [s for s in candidates if s.snapshot_date == latest]
                costs_at_snapshot = {s.unit_cost for s in candidates}
                if len(costs_at_snapshot) == 1 and None not in costs_at_snapshot:
                    actual[f.id] = f.quantity_sold * candidates[0].unit_cost
                    dependencies[f.id] = candidates
    branch = {}
    groups = [('branch',stores[s],by_store[s]) for s in sorted(by_store)] + [('company',company_id,sales)]
    for kind,entity,rows in groups:
        revenue = total(f.revenue for f in rows) if rows else None
        coverage = sum(f.id in actual for f in rows)/len(rows) if rows else 0
        cogs = total(actual[f.id] for f in rows) if rows and coverage == 1 else None
        profit = revenue-cogs if revenue is not None and cogs is not None else None
        margin = profit/revenue*100 if profit is not None and revenue and revenue > 0 else None
        issues = ['missing_sales'] if not rows else (['missing_cost'] if coverage < 1 else [])
        for name,value,unit,formula in [('revenue',revenue,'TRY','sum(net revenue)'),('cogs',cogs,'TRY','sum(point-in-time line COGS)'),
            ('gross_profit',profit,'TRY','revenue - cogs'),('gross_margin_pct',margin,'%','gross_profit / positive revenue * 100')]:
            facts=rows if name=='revenue' else rows+[source for f in rows for source in dependencies.get(f.id,[])]
            metric_issues = (['missing_sales'] if not rows else []) if name == 'revenue' else list(issues)
            if name == 'gross_margin_pct' and (revenue is None or revenue <= 0):
                metric_issues.append('missing_positive_revenue')
            emit(kind,entity,name,value,unit,facts,formula,metric_issues,(1.0 if rows else 0.0) if name == 'revenue' else coverage)
        if kind == 'branch':
            branch[entity] = (revenue,cogs,margin)
    margins = {s:v[2] for s,v in branch.items() if v[2] is not None}
    if len(margins) >= 2 and len(margins) == len(branch):
        best,worst = max(margins,key=margins.get),min(margins,key=margins.get)
        gap = margins[best]-margins[worst]
        margin_facts = sales + [c for sources in dependencies.values() for c in sources]
        emit('company',company_id,'branch_margin_gap_pct',gap,'pp',margin_facts,f'margin[{best}] - margin[{worst}]')
        emit('company',company_id,'branch_margin_gap_try',gap/100*branch[worst][0],'TRY',margin_facts,'margin gap / 100 * worst branch revenue (scenario, not savings)')
    pairs = defaultdict(list)
    for f in sales:
        pairs[(f.store_id,f.product_id)].append(f)
    for (store,product),rows in pairs.items():
        comparable = [(f,resolve(f, budget=True)) for f in rows]
        if not all(c and c.is_budget and f.id in actual for f,c in comparable):
            continue  # Observed supplier cost is not an approved budget baseline.
        standard = total(f.quantity_sold*c.standard_unit_cost for f,c in comparable)
        delta = total(actual[f.id] for f in rows)-standard
        entity = f'{stores[store]}:{products[product]}'
        variance_facts = rows + [c for _, c in comparable] + [c for f in rows for c in dependencies.get(f.id, [])]
        emit('branch_product',entity,'unit_cost_variance_pct',delta/standard*100 if standard > 0 else None,'%',variance_facts,'(actual line COGS - approved budget COGS) / budget COGS * 100')
        emit('branch_product',entity,'unit_cost_variance_try',delta,'TRY',variance_facts,'actual line COGS - approved budget COGS')
    stock_groups = defaultdict(list)
    for f in inventory:
        if f.store_id not in stores or f.product_id not in products:
            raise InvalidSourceDataError('Unresolved canonical inventory reference')
        stock_groups[f.store_id].append(f)
    for store,rows in stock_groups.items():
        entity = stores[store]
        issues = []
        if any((period.end-f.snapshot_date).days > get_settings().inventory_max_age_days for f in rows): issues.append('stale_inventory')
        if any(f.inventory_value is None and f.unit_cost is None for f in rows): issues.append('missing_inventory_cost')
        value = None if issues else total(f.inventory_value if f.inventory_value is not None else f.quantity*f.unit_cost for f in rows)
        revenue,cogs,_ = branch.get(entity,(None,None,None))
        dio = value/cogs*period.days if value is not None and cogs and cogs > 0 else None
        wc = value/revenue*100 if value is not None and revenue and revenue > 0 else None
        for metric,val,unit,formula in [('inventory_value',value,'TRY','sum(ending snapshot inventory value)'),
            ('days_inventory_outstanding',dio,'days','ending inventory / positive period COGS * period days (ending-stock proxy)'),
            ('working_capital_in_inventory_pct',wc,'%','ending inventory / positive period revenue * 100')]:
            metric_issues = list(issues)
            facts = list(rows)
            if metric != 'inventory_value':
                facts += by_store[store]
            if metric == 'days_inventory_outstanding':
                facts += [c for f in by_store[store] for c in dependencies.get(f.id, [])]
                if cogs is None or cogs <= 0: metric_issues.append('missing_positive_cogs')
            if metric == 'working_capital_in_inventory_pct' and (revenue is None or revenue <= 0):
                metric_issues.append('missing_positive_revenue')
            if metric == 'working_capital_in_inventory_pct' and not (
                    period.start.day == 1 and period.start.year == period.end.year
                    and period.start.month == period.end.month
                    and period.end.day == calendar.monthrange(period.end.year, period.end.month)[1]):
                metric_issues.append('monthly_threshold_period_basis_unverified')
            emit('branch',entity,metric,val,unit,facts,formula,metric_issues,0 if val is None else 1,min(f.snapshot_date for f in rows).isoformat())
    wastes = defaultdict(list)
    for f in waste:
        if f.event_type == 'waste': wastes[f.store_id].append(f)
    for store,rows in wastes.items():
        amounts = []
        waste_dependencies = []
        for f in rows:
            c = resolve(f)
            amounts.append(None if not f.cost_basis_known else f.cost_amount if f.cost_amount is not None else (f.quantity*c.standard_unit_cost if c else None))
            if f.cost_basis_known and f.cost_amount is None and c is not None:
                waste_dependencies.append(c)
        value = total(amounts) if all(v is not None for v in amounts) else None
        entity = stores[store]
        revenue = branch.get(entity,(None,None,None))[0]
        pct = value/revenue*100 if value is not None and revenue and revenue > 0 else None
        for metric,val,unit,formula in [('waste_value_try',value,'TRY','sum(event-time waste cost)'),('waste_to_revenue_pct',pct,'%','waste cost / positive revenue * 100')]:
            facts = rows + waste_dependencies + (by_store[store] if metric == 'waste_to_revenue_pct' else [])
            issues = ['missing_waste_cost'] if value is None else []
            if metric == 'waste_to_revenue_pct' and (revenue is None or revenue <= 0): issues.append('missing_positive_revenue')
            emit('branch',entity,metric,val,unit,facts,formula,issues,sum(v is not None for v in amounts)/len(amounts))
    return result

