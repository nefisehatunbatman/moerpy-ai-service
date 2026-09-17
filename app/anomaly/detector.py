"""Anomaly detection: compares KPI results against company thresholds.

Entirely deterministic — no LLM, no invented causality. Each anomaly is a
straight comparison of an actual, already-computed KPI value against a
persisted company threshold.
"""

import hashlib
import json
from datetime import datetime, timezone

from app.anomaly.schemas import Anomaly
from app.anomaly.severity import compute_severity
from app.core.logging import get_logger
from app.data.models import Period
from app.kpi.models import KpiResult, PeriodOut
from app.thresholds.engine import evaluate
from app.thresholds.models import CompanyThreshold
from app.evidence.selection import snapshot_candidates, SELECTION_VERSION
from app.core.errors import InvalidSourceDataError

logger = get_logger(__name__)


def _stable_id(company_id: str, metric: str, entity_id: str, period: Period) -> str:
    raw = f"{company_id}|{metric}|{entity_id}|{period.start.isoformat()}|{period.end.isoformat()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"ANO-{digest}"


def detect_anomalies(
    company_id: str,
    period: Period,
    kpi_results: list[KpiResult],
    thresholds: list[CompanyThreshold],
) -> list[Anomaly]:
    if any(k.company_id != company_id or k.period != PeriodOut.from_period(period) for k in kpi_results):
        raise InvalidSourceDataError('KPI scope does not match the analysis')
    if len({k.tenant_id for k in kpi_results}) > 1:
        raise InvalidSourceDataError('Mixed tenant KPI snapshot')
    keys = [(k.entity_type, k.entity_id, k.metric) for k in kpi_results]
    if len(keys) != len(set(keys)):
        raise InvalidSourceDataError('Duplicate KPI in analysis')
    threshold_by_metric = {t.metric: t for t in thresholds if t.active}
    period_out = PeriodOut.from_period(period)
    anomalies: list[Anomaly] = []
    snapshot = [k.model_dump(exclude={'calculated_at'}) for k in sorted(kpi_results,key=lambda k:(k.entity_type,k.entity_id,k.metric))]
    policies = [dict(metric=t.metric,operator=t.operator,warning_value=t.warning_value,critical_value=t.critical_value,
                     active=t.active,department=t.department) for t in sorted(thresholds,key=lambda t:t.metric)]
    run_id = hashlib.sha256(json.dumps({'kpis':snapshot,'thresholds':policies,'context_version':SELECTION_VERSION},sort_keys=True).encode()).hexdigest()[:24]

    for kpi in kpi_results:
        if kpi.value is None or kpi.status != 'ok':
            continue
        threshold = threshold_by_metric.get(kpi.metric)
        if threshold is None:
            # No company policy for this metric — not evaluated, never assumed anomalous.
            continue

        evaluation = evaluate(
            metric=kpi.metric,
            entity_type=kpi.entity_type,
            entity_id=kpi.entity_id,
            actual_value=kpi.value,
            threshold=threshold,
        )
        logger.info(
            "threshold_evaluated",
            extra={
                "company_id": company_id,
                "metric": kpi.metric,
                "entity_id": kpi.entity_id,
                "status": evaluation.status,
            },
        )
        if evaluation.status in ('ok', 'not_evaluated'):
            continue

        severity = compute_severity(
            actual_value=kpi.value,
            warning_value=threshold.warning_value,
            critical_value=threshold.critical_value,
            status=evaluation.status,
        )

        anomaly = Anomaly(
            id=_stable_id(company_id, kpi.metric, kpi.entity_id, period)+'-'+run_id[:12],
            company_id=company_id,
            tenant_id=kpi.tenant_id, run_id=run_id,
            kpi_snapshot=[r.model_dump() for r in snapshot_candidates(kpi, kpi_results)],
            threshold_snapshot=[t for t in policies if t['metric']==kpi.metric],
            entity_type=kpi.entity_type,
            entity_ids=[kpi.entity_id],
            metric=kpi.metric,
            actual_value=kpi.value,
            threshold_value=evaluation.threshold_value,
            deviation=evaluation.deviation,
            severity=severity or "low",
            department=threshold.department,
            period=period_out,
            detected_at=datetime.now(timezone.utc).isoformat(),
        )
        anomalies.append(anomaly)
        logger.info(
            "anomaly_detected",
            extra={"company_id": company_id, "anomaly_id": anomaly.id, "severity": anomaly.severity},
        )

    return anomalies
