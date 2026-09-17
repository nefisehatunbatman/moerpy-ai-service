from datetime import date

import pytest

from app.anomaly.detector import detect_anomalies
from app.anomaly.repository import AnomalyRepository
from app.data.models import Period
from app.data.providers.fake_provider import FakeERPDataProvider
from app.kpi.engine import compute_kpis
from app.thresholds.defaults import get_seed_thresholds
from app.thresholds.repository import ThresholdRepository

FEB = Period(start=date(2026, 2, 1), end=date(2026, 2, 28))


def _anomalies_for(company_id, db_session):
    ThresholdRepository(db_session).seed_if_empty(company_id, get_seed_thresholds(company_id))
    thresholds = ThresholdRepository(db_session).list_for_company(company_id)
    kpis = compute_kpis(FakeERPDataProvider(), company_id, FEB)
    return detect_anomalies(company_id, FEB, kpis, thresholds)


def test_comp002_healthy_company_has_zero_anomalies(db_session):
    anomalies = _anomalies_for("COMP-002", db_session)
    assert anomalies == []


def test_comp001_working_capital_is_critical(db_session):
    anomalies = _anomalies_for("COMP-001", db_session)
    wc = next(a for a in anomalies if a.metric == "working_capital_in_inventory_pct" and a.entity_ids == ["BR-002"])
    assert wc.severity == "critical"


def test_comp001_unit_cost_variance_is_medium(db_session):
    anomalies = _anomalies_for("COMP-001", db_session)
    variance = next(a for a in anomalies if a.metric == "unit_cost_variance_pct" and a.entity_ids == ["BR-002:PRD-001"])
    assert variance.severity == "medium"


def test_comp001_produces_multiple_distinct_anomalies(db_session):
    anomalies = _anomalies_for("COMP-001", db_session)
    assert len(anomalies) >= 5
    # BR-001 (the healthy branch) should not show up as an anomalous unit-cost-variance entity
    assert not any(a.metric == "unit_cost_variance_pct" and a.entity_ids[0].startswith("BR-001") for a in anomalies)


def test_detection_is_idempotent(db_session):
    anomalies = _anomalies_for("COMP-001", db_session)
    ids = [a.id for a in anomalies]
    assert len(ids) == len(set(ids))

    repo = AnomalyRepository(db_session)
    repo.save_all(anomalies)
    repo.save_all(anomalies)  # re-running detection must not duplicate rows
    assert len(repo.list_for_company("COMP-001")) == len(anomalies)


def test_metric_without_company_threshold_is_never_flagged(db_session):
    # gross_profit has no threshold configured anywhere — must be silently skipped, not guessed.
    anomalies = _anomalies_for("COMP-001", db_session)
    assert not any(a.metric == "gross_profit" for a in anomalies)
