from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.thresholds.models import CompanyThreshold
from app.thresholds.schemas import ThresholdIn


class ThresholdRepository:
    def __init__(self, session: Session, tenant_id='fixture-tenant') -> None:
        self.session = session
        self.tenant_id=tenant_id

    def list_for_company(self, company_id: str, active_only: bool = True) -> list[CompanyThreshold]:
        stmt = select(CompanyThreshold).where(CompanyThreshold.company_id == company_id,CompanyThreshold.tenant_id==self.tenant_id).order_by(CompanyThreshold.metric)
        if active_only:
            stmt = stmt.where(CompanyThreshold.active.is_(True))
        return list(self.session.scalars(stmt))

    def upsert(self, company_id: str, threshold: ThresholdIn) -> CompanyThreshold:
        existing = self.session.scalar(
            select(CompanyThreshold).where(
                CompanyThreshold.company_id == company_id,
                CompanyThreshold.tenant_id==self.tenant_id,
                CompanyThreshold.metric == threshold.metric,
            )
        )
        if existing:
            existing.operator = threshold.operator
            existing.warning_value = threshold.warning_value
            existing.critical_value = threshold.critical_value
            existing.department = threshold.department
            existing.active = threshold.active
            row = existing
        else:
            row = CompanyThreshold(company_id=company_id,tenant_id=self.tenant_id, **threshold.model_dump())
            self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def seed_if_empty(self, company_id: str, defaults: list[ThresholdIn]) -> None:
        if self.list_for_company(company_id, active_only=False):
            return
        for threshold in defaults:
            self.session.add(CompanyThreshold(company_id=company_id,tenant_id=self.tenant_id, **threshold.model_dump()))
        try: self.session.commit()
        except IntegrityError:
            self.session.rollback()
            if not self.list_for_company(company_id,active_only=False): raise
