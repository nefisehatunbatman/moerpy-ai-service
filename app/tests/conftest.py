import os
os.environ.update(AI_SERVICE_DATABASE_URL='sqlite://',ERP_PROVIDER='fake',ERP_DATABASE_URL='',LLM_API_KEY='',EMBEDDING_API_KEY='',
                  AI_SERVICE_INTERNAL_TOKEN='test-context-secret-with-more-than-32-characters',ENVIRONMENT='test')
os.environ.update(LLM_MODE='offline',EMBEDDING_MODE='local')
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base

@pytest.fixture
def client():
    import httpx
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from main import app
    from app.api.deps import get_db
    from app.api.security import signed_headers
    from app.core.config import get_settings
    test_engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(test_engine)
    def db_override():
        with Session(test_engine) as session: yield session
    app.dependency_overrides[get_db]=db_override
    class SignedClient(TestClient):
        company_id='COMP-001'
        tenant_id='fixture-tenant'
        roles=['finance']
        def request(self,method,url,**kwargs):
            custom=kwargs.pop('headers',{}) or {}
            req=httpx.Request(method,self.base_url.join(url),**{k:v for k,v in kwargs.items() if k in ('params','json','content','data','files')})
            req.headers.update(signed_headers(get_settings().ai_service_internal_token,method,req.url.raw_path.decode(),req.read(),
                tenant_id=self.tenant_id,company_id=self.company_id,actor='test-cfo',roles=self.roles))
            req.headers.update(custom)
            return self.send(req)
    # No production lifespan: overrides own schema and connection lifecycle.
    c=SignedClient(app,raise_server_exceptions=False)
    yield c
    c.close(); app.dependency_overrides.clear(); test_engine.dispose()


@pytest.fixture
def db_session():
    """Fresh in-memory SQLite database per test — fast, isolated, no file I/O."""
    # Import models so they register on Base.metadata.
    from app.anomaly import models as _anomaly_models  # noqa: F401
    from app.decisions import models as _decisions_models  # noqa: F401
    from app.rag import models as _rag_models  # noqa: F401
    from app.thresholds import models as _thresholds_models  # noqa: F401

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()
