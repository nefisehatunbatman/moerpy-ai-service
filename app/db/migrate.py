"""Additive v2 upgrade of the AI database only. Old unscoped rows remain inaccessible."""
from datetime import datetime
from pathlib import Path
from sqlalchemy import inspect,text
from app.db.base import engine,Base
from app.anomaly import models
from app.decisions import models
from app.rag import models
from app.thresholds import models

def migrate():
    if engine.url.get_backend_name()=='sqlite' and engine.url.database and engine.url.database!=':memory:':
        path=Path(engine.url.database)
        if path.exists():
            import sqlite3
            backup=path.with_suffix('.backup-'+datetime.now().strftime('%Y%m%d%H%M%S%f')+'.db')
            with sqlite3.connect(path) as source,sqlite3.connect(backup) as dest: source.backup(dest)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        inspector=inspect(conn)
        for table in Base.metadata.sorted_tables:
            existing={c['name'] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing: continue
                sqltype=col.type.compile(dialect=engine.dialect)
                if col.name=='tenant_id': default="'legacy-unscoped'"
                elif col.name in ('active',): default='false'
                elif col.name in ('embedding_dimensions',): default='0'
                elif str(col.type)=='JSON': default="'{}'" if col.name=='confidence_factors' else "'[]'"
                elif 'DATE' in str(col.type): default='NULL'
                else: default="''"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {sqltype} DEFAULT {default}'))
        conn.execute(text('CREATE TABLE IF NOT EXISTS ai_schema_version (version INTEGER PRIMARY KEY)'))
        conn.execute(text('UPDATE knowledge_base_entries SET tenant_id=NULL WHERE company_id IS NULL'))
        conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_scope_metric_v2 ON company_thresholds(tenant_id,company_id,metric)'))
        if conn.execute(text('SELECT COUNT(*) FROM ai_schema_version WHERE version=2')).scalar()==0:
            conn.execute(text('INSERT INTO ai_schema_version VALUES (2)'))
    from sqlalchemy.orm import Session
    from app.rag.migration import repair_global_learning
    with Session(engine) as session, session.begin():
        repair_global_learning(session)
        if not session.execute(text('SELECT COUNT(*) FROM ai_schema_version WHERE version=3')).scalar():
            session.execute(text('INSERT INTO ai_schema_version VALUES (3)'))

if __name__=='__main__':
    migrate()
    print('AI database upgraded through v3; legacy learning isolated. Re-run analysis and reindex legacy embeddings before use.')
