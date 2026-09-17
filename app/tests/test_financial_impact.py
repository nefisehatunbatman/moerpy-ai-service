from datetime import date

from app.anomaly.detector import detect_anomalies
from app.data.models import Period
from app.data.providers.fake_provider import FakeERPDataProvider
from app.financial_impact.analyzer import analyze
from app.kpi.engine import compute_kpis
from app.thresholds.defaults import get_seed_thresholds
from app.thresholds.repository import ThresholdRepository

FEB = Period(start=date(2026, 2, 1), end=date(2026, 2, 28))


def test_working_capital_anomaly_gets_quantitative_impact(db_session):
    ThresholdRepository(db_session).seed_if_empty("COMP-001", get_seed_thresholds("COMP-001"))
    thresholds = ThresholdRepository(db_session).list_for_company("COMP-001")
    kpis = compute_kpis(FakeERPDataProvider(), "COMP-001", FEB)
    anomalies = detect_anomalies("COMP-001", FEB, kpis, thresholds)

    wc_anomaly = next(a for a in anomalies if a.metric == "working_capital_in_inventory_pct")
    impact = analyze(wc_anomaly, kpis)

    assert impact.decision_type is None
    assert impact.department == "finance"
    assert impact.quantified_impact is not None
    assert impact.quantified_impact.value == 492000  # BR-002 inventory_value, verified in test_kpi_engine
    assert "nedensellik" in impact.causation_caveat


def test_unit_cost_variance_anomaly_maps_to_cost_optimization(db_session):
    ThresholdRepository(db_session).seed_if_empty("COMP-001", get_seed_thresholds("COMP-001"))
    thresholds = ThresholdRepository(db_session).list_for_company("COMP-001")
    kpis = compute_kpis(FakeERPDataProvider(), "COMP-001", FEB)
    anomalies = detect_anomalies("COMP-001", FEB, kpis, thresholds)

    variance_anomaly = next(a for a in anomalies if a.metric == "unit_cost_variance_pct" and a.entity_ids == ["BR-002:PRD-001"])
    impact = analyze(variance_anomaly, kpis)

    assert impact.decision_type is None
    assert "procurement" in impact.support_departments
    assert impact.quantified_impact.value == (430 - 350) * 200  # 16000 TRY


def test_unknown_metric_requires_review_instead_of_guessing():
    from app.anomaly.schemas import Anomaly
    from app.kpi.models import PeriodOut
    import pytest

    fake_anomaly = Anomaly(tenant_id='fixture-tenant',
        id="ANO-x",
        company_id="COMP-001",
        entity_type="branch",
        entity_ids=["BR-001"],
        metric="not_a_real_metric",
        actual_value=1,
        threshold_value=1,
        deviation=0,
        severity="low",
        department="finance",
        period=PeriodOut(start="2026-02-01", end="2026-02-28"),
        detected_at="2026-02-28T00:00:00Z",
    )
    impact = analyze(fake_anomaly, [])
    assert impact.assessment_status == 'review_required'
    assert impact.quantified_impact is None
    assert 'unmapped_financial_context' in impact.information_gaps


