from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.anomaly.models import AnomalyRecord
from app.anomaly.schemas import Anomaly


class AnomalyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_all(self, anomalies: list[Anomaly], company_id=None, period=None, tenant_id='fixture-tenant') -> None:
        if anomalies:
            company_id=anomalies[0].company_id
            tenant_id=anomalies[0].tenant_id
            from app.data.models import Period
            from datetime import date
            period=Period(date.fromisoformat(anomalies[0].period.start),date.fromisoformat(anomalies[0].period.end))
            if any(a.company_id != company_id or a.tenant_id != tenant_id
                   or a.period.start != str(period.start) or a.period.end != str(period.end) for a in anomalies):
                raise ValueError('Mixed anomaly scope or period')
        if company_id and period:
            self.session.execute(update(AnomalyRecord).where(AnomalyRecord.company_id==company_id,
                AnomalyRecord.tenant_id==tenant_id,
                AnomalyRecord.period_start==str(period.start),AnomalyRecord.period_end==str(period.end)).values(active=False))
        for anomaly in anomalies:
            existing = self.session.get(AnomalyRecord, anomaly.id)
            if existing:
                existing.active=True
                continue  # detection is idempotent: same id => same anomaly, keep first detected_at
            self.session.add(
                AnomalyRecord(
                    id=anomaly.id,
                    company_id=anomaly.company_id,
                    tenant_id=anomaly.tenant_id,run_id=anomaly.run_id,active=True,
                    kpi_snapshot=anomaly.kpi_snapshot,threshold_snapshot=anomaly.threshold_snapshot,
                    entity_type=anomaly.entity_type,
                    entity_id=anomaly.entity_id,
                    metric=anomaly.metric,
                    actual_value=anomaly.actual_value,
                    threshold_value=anomaly.threshold_value,
                    deviation=anomaly.deviation,
                    severity=anomaly.severity,
                    department=anomaly.department,
                    period_start=anomaly.period.start,
                    period_end=anomaly.period.end,
                )
            )
        self.session.commit()

    def get(self, anomaly_id: str) -> AnomalyRecord | None:
        return self.session.get(AnomalyRecord, anomaly_id)

    def list_for_company(self, company_id: str, limit=100, offset=0, tenant_id='fixture-tenant') -> list[AnomalyRecord]:
        stmt = select(AnomalyRecord).where(AnomalyRecord.company_id == company_id,AnomalyRecord.tenant_id == tenant_id,AnomalyRecord.active.is_(True)).order_by(AnomalyRecord.id).limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    @staticmethod
    def to_schema(record: AnomalyRecord) -> Anomaly:
        from app.kpi.models import PeriodOut

        return Anomaly(
            id=record.id,
            company_id=record.company_id,
            tenant_id=record.tenant_id,run_id=record.run_id,kpi_snapshot=record.kpi_snapshot,threshold_snapshot=record.threshold_snapshot,
            entity_type=record.entity_type,
            entity_ids=[record.entity_id],
            metric=record.metric,
            actual_value=record.actual_value,
            threshold_value=record.threshold_value,
            deviation=record.deviation,
            severity=record.severity,
            department=record.department,
            period=PeriodOut(start=record.period_start, end=record.period_end),
            detected_at=record.detected_at.isoformat(),
        )
