from datetime import date

from app.anomaly.detector import detect_anomalies
from app.data.models import Period
from app.data.providers.fake_provider import FakeERPDataProvider
from app.evidence.builder import build_evidence
from app.financial_impact.analyzer import analyze
from app.kpi.engine import compute_kpis
from app.thresholds.defaults import get_seed_thresholds
from app.thresholds.repository import ThresholdRepository

FEB = Period(start=date(2026, 2, 1), end=date(2026, 2, 28))


def test_evidence_package_for_cash_locked_anomaly(db_session):
    repo = ThresholdRepository(db_session)
    repo.seed_if_empty("COMP-001", get_seed_thresholds("COMP-001"))
    thresholds = repo.list_for_company("COMP-001")
    kpis = compute_kpis(FakeERPDataProvider(), "COMP-001", FEB)
    anomalies = detect_anomalies("COMP-001", FEB, kpis, thresholds)

    anomaly = next(a for a in anomalies if a.metric == "working_capital_in_inventory_pct")
    impact = analyze(anomaly, kpis)
    evidence = build_evidence(anomaly, impact, kpis, thresholds)

    assert evidence.decision_type is None
    assert evidence.severity == "critical"
    metric_names = {s.metric for s in evidence.signals}
    assert "working_capital_in_inventory_pct" in metric_names
    assert "inventory_value" in metric_names
    assert "revenue" in metric_names
    assert evidence.quantified_impact.value == 492000
    assert len(evidence.thresholds) == 1
    assert evidence.thresholds[0].critical_value == 100


def test_evidence_package_never_invents_missing_context_signal(db_session):
    # COMP-002 has no branch_margin_gap (single branch) so a manually built
    # anomaly for it must not fabricate a context signal that doesn't exist.
    from app.anomaly.schemas import Anomaly
    from app.kpi.models import PeriodOut

    anomaly = Anomaly(tenant_id='fixture-tenant',
        id="ANO-test",
        company_id="COMP-002",
        entity_type="company",
        entity_ids=["COMP-002"],
        metric="branch_margin_gap_pct",
        actual_value=99,
        threshold_value=8,
        deviation=91,
        severity="critical",
        department="finance",
        period=PeriodOut(start="2026-02-01", end="2026-02-28"),
        detected_at="2026-02-28T00:00:00Z",
    )
    impact = analyze(anomaly, [])
    evidence = build_evidence(anomaly, impact, [], [])

    assert evidence.signals == []  # no own KPI, no context KPI supplied — nothing fabricated


