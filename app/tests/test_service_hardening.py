"""Regressions for isolation, provenance and incomplete inputs in the AI service."""
from dataclasses import replace
from datetime import date

import pytest

from app.data.models import CostFact, InventoryFact, WasteReturnFact
from app.kpi.engine import compute_kpis
from app.rag.embeddings import LocalHashEmbedding
from app.rag.knowledge_base import KnowledgeBaseRepository
from app.tests.test_regressions import FEB, SmallProvider, company_metric, sale


def test_company_learning_never_mutates_global_templates(db_session):
    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding(), 'tenant-a')
    kb.seed_if_empty()
    template = kb.get('KB-0003')
    fields = dict(company_id='company-a', problem_type=template.problem_type,
                  decision_type=template.decision_type, department='finance', signals=[],
                  conditions={}, decision_text=template.decision_text,
                  financial_objective=template.financial_objective, expected_effect=template.expected_effect)
    learned = kb.record_approved_decision(**fields, source_decision_id='decision-a')
    assert learned.company_id == 'company-a'
    assert learned.tenant_id == 'tenant-a'
    assert template.company_contexts == []
    assert template.approval_count == 0
    foreign = KnowledgeBaseRepository(db_session, LocalHashEmbedding(), 'tenant-b')
    assert learned.id not in {entry.id for entry in foreign.list_all('company-b')}
    second = kb.record_approved_decision(**fields, source_decision_id='decision-a')
    assert second.id == learned.id and second.approval_count == 1


def test_revenue_quality_does_not_depend_on_cost_availability():
    result = compute_kpis(SmallProvider([sale('sale', None)]), 'C', FEB)
    assert company_metric(result, 'revenue').status == 'ok'
    assert company_metric(result, 'revenue').coverage == 1
    assert company_metric(result, 'cogs').value is None


def test_stock_value_quality_does_not_depend_on_sales():
    stock = InventoryFact('stock', 'C', 'S', 'P', FEB.end, 100, 10,tenant_id='fixture-tenant')
    result = compute_kpis(SmallProvider(inventory=[stock]), 'C', FEB)
    metric = next(k for k in result if k.metric == 'inventory_value')
    assert metric.value == 1000 and metric.status == 'ok'


def test_dio_provenance_includes_sales_and_resolved_cost():
    cost = CostFact('cost', 'C', 'P', FEB, 10, 'TRY', 'supplier',tenant_id='fixture-tenant', is_budget=False)
    stock = InventoryFact('stock', 'C', 'S', 'P', FEB.end, 100, 10,tenant_id='fixture-tenant')
    result = compute_kpis(SmallProvider([sale('sale', None)], [stock], [cost]), 'C', FEB)
    dio = next(k for k in result if k.metric == 'days_inventory_outstanding')
    assert {'SalesFact:sale', 'CostFact:cost', 'InventoryFact:stock'} <= set(dio.source_ids)


def test_zero_cogs_does_not_hide_inventory_revenue_ratio():
    stock = InventoryFact('stock', 'C', 'S', 'P', FEB.end, 100, 10,tenant_id='fixture-tenant')
    result = compute_kpis(SmallProvider([sale('sale', 0)], [stock]), 'C', FEB)
    ratio = next(k for k in result if k.metric == 'working_capital_in_inventory_pct')
    assert ratio.value == 1000 and ratio.status == 'ok'
    assert next(k for k in result if k.metric == 'days_inventory_outstanding').value is None


def test_duplicate_sales_ids_are_rejected_instead_of_overwriting_cost():
    with pytest.raises(ValueError, match='Duplicate'):
        compute_kpis(SmallProvider([sale('same', 10), sale('same', 20)]), 'C', FEB)


def test_conflicting_inventory_fallback_is_not_order_dependent():
    stocks = [InventoryFact('one', 'C', 'S', 'P', FEB.end, 10, 10,tenant_id='fixture-tenant'),
              InventoryFact('two', 'C', 'S', 'P', FEB.end, 20, 20,tenant_id='fixture-tenant')]
    for order in (stocks, list(reversed(stocks))):
        result = compute_kpis(SmallProvider([sale('sale', None, 28)], order), 'C', FEB)
        assert company_metric(result, 'cogs').value is None


def test_equal_priority_conflicting_costs_are_rejected():
    costs = [CostFact('a', 'C', 'P', FEB, 10, 'TRY', 'supplier',tenant_id='fixture-tenant'),
             CostFact('b', 'C', 'P', FEB, 20, 'TRY', 'supplier',tenant_id='fixture-tenant')]
    with pytest.raises(ValueError, match='Conflicting'):
        compute_kpis(SmallProvider([sale('sale', None)], costs=costs), 'C', FEB)


def test_budget_does_not_substitute_for_missing_actual_cost():
    budget = CostFact('budget', 'C', 'P', FEB, 10, 'TRY', 'supplier',tenant_id='fixture-tenant', is_budget=True)
    result = compute_kpis(SmallProvider([sale('sale', None)], costs=[budget]), 'C', FEB)
    assert company_metric(result, 'cogs').value is None


def test_actual_cost_and_budget_are_resolved_independently():
    budget = CostFact('budget', 'C', 'P', FEB, 10, 'TRY', 'supplier',tenant_id='fixture-tenant', is_budget=True)
    actual = CostFact('actual', 'C', 'P', FEB, 12, 'TRY', 'supplier',tenant_id='fixture-tenant', is_budget=False,
                      effective_date=date(2026, 2, 1))
    result = compute_kpis(SmallProvider([sale('sale', None)], costs=[budget, actual]), 'C', FEB)
    assert company_metric(result, 'cogs').value == 12
    variance = next(k for k in result if k.metric == 'unit_cost_variance_pct')
    assert variance.value == 20
    assert {'CostFact:budget', 'CostFact:actual'} <= set(variance.source_ids)


def test_provider_cannot_return_future_stock():
    stock = InventoryFact('stock', 'C', 'S', 'P', date(2026, 3, 1), 100, 10,tenant_id='fixture-tenant')
    with pytest.raises(ValueError, match='period|future'):
        compute_kpis(SmallProvider(inventory=[stock]), 'C', FEB)


def test_unknown_waste_reference_is_a_validation_error():
    provider = SmallProvider([sale('sale', 10)])
    provider.get_waste_return_facts = lambda *_: [WasteReturnFact(
        'waste', 'C', 'unknown-store', 'P', FEB.end, 'waste', 1, 'test', tenant_id='fixture-tenant', cost_amount=10)]
    with pytest.raises(ValueError, match='Unresolved'):
        compute_kpis(provider, 'C', FEB)


def test_cost_derived_waste_has_cost_provenance():
    cost = CostFact('cost', 'C', 'P', FEB, 10, 'TRY', 'supplier',tenant_id='fixture-tenant', is_budget=False)
    provider = SmallProvider([sale('sale', 10)], costs=[cost])
    provider.get_waste_return_facts = lambda *_: [WasteReturnFact('waste', 'C', 'S', 'P', FEB.end, 'waste', 1, 'test',tenant_id='fixture-tenant')]
    result = compute_kpis(provider, 'C', FEB)
    metric = next(k for k in result if k.metric == 'waste_to_revenue_pct')
    assert {'CostFact:cost', 'WasteReturnFact:waste', 'SalesFact:sale'} <= set(metric.source_ids)

