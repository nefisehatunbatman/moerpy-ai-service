from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.engine import make_url

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    url = settings.ai_service_database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    url=make_url(url)
    if url.drivername in ('postgres','postgresql'): url=url.set(drivername='postgresql+psycopg')
    return create_engine(url, connect_args=connect_args)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    # Import models so they register on Base.metadata before create_all.
    from app.thresholds import models as _thresholds_models  # noqa: F401
    from app.anomaly import models as _anomaly_models  # noqa: F401
    from app.decisions import models as _decisions_models  # noqa: F401
    from app.rag import models as _rag_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    from sqlalchemy import inspect
    inspector=inspect(engine)
    for table in Base.metadata.sorted_tables:
        existing={c['name'] for c in inspector.get_columns(table.name)}
        if set(table.columns.keys())-existing:
            raise RuntimeError('Database needs an upgrade: run python -m app.db.migrate after backup')

