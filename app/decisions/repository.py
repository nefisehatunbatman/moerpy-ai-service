from sqlalchemy import select,update
from sqlalchemy.orm import Session

from app.decisions.models import DecisionLifecycleEvent, DecisionRecord


class DecisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, record: DecisionRecord) -> DecisionRecord:
        self.session.add(record)
        self.log_event(record.id,from_status=None,to_status='GENERATING',actor='system')
        self.log_event(record.id,from_status='GENERATING',to_status=record.status,actor='system')
        self.session.commit()
        self.session.refresh(record)
        return record

    def get(self, decision_id: str) -> DecisionRecord | None:
        return self.session.get(DecisionRecord, decision_id)

    def list_for_company(self, company_id: str, status: str | None = None,limit=100,offset=0,tenant_id='fixture-tenant') -> list[DecisionRecord]:
        stmt = select(DecisionRecord).where(DecisionRecord.company_id == company_id, DecisionRecord.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(DecisionRecord.status == status)
        return list(self.session.scalars(stmt.order_by(DecisionRecord.created_at.desc(),DecisionRecord.id).limit(limit).offset(offset)))

    def transition(self, record: DecisionRecord, to_status: str, actor: str | None, note: str | None = None, **fields) -> None:
        from_status = record.status
        result=self.session.execute(update(DecisionRecord).where(DecisionRecord.id==record.id,DecisionRecord.status==from_status).values(status=to_status,**fields),execution_options={'synchronize_session':False})
        if result.rowcount!=1:
            self.session.rollback()
            from app.decisions.service import InvalidDecisionTransitionError
            raise InvalidDecisionTransitionError('Decision was changed by another request')
        self.log_event(record.id, from_status=from_status, to_status=to_status, actor=actor, note=note)
        self.session.commit()
        self.session.refresh(record)

    def log_event(
        self, decision_id: str, *, from_status: str | None, to_status: str, actor: str | None, note: str | None = None
    ) -> None:
        self.session.add(
            DecisionLifecycleEvent(
                decision_id=decision_id, from_status=from_status, to_status=to_status, actor=actor, note=note
            )
        )

    def lifecycle(self, decision_id: str) -> list[DecisionLifecycleEvent]:
        stmt = (
            select(DecisionLifecycleEvent)
            .where(DecisionLifecycleEvent.decision_id == decision_id)
            .order_by(DecisionLifecycleEvent.occurred_at)
        )
        return list(self.session.scalars(stmt))
