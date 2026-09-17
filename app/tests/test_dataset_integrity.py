import hashlib
import json
import sqlite3
from pathlib import Path
import pytest
from app.data.business import ingest

def test_corrupt_source_is_never_published(tmp_path):
    source=tmp_path/'source';source.mkdir()
    (source/'companies-00001.csv').write_text('company_id,tenant_id\nC,T\n',encoding='utf-8')
    manifest={'profile':'demo','dataset_name':'moerpy_fictional_seafood_24m','company_id':'C',
        'tables':{'companies':{'columns':['company_id','tenant_id'],'files':[{'path':'companies-00001.csv','sha256':'wrong','rows':1}],'row_count':1}}}
    (source/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    target=tmp_path/'output.db'
    with pytest.raises(ValueError,match='Checksum'): ingest(source,target)
    assert not target.exists()

def test_private_oracle_path_cannot_be_ingested(tmp_path):
    (tmp_path/'manifest.json').write_text(json.dumps({'profile':'private_oracle'}))
    with pytest.raises(ValueError,match='main demo'): ingest(tmp_path,tmp_path/'output.db')

def test_existing_dataset_cannot_be_overwritten(tmp_path):
    target=tmp_path/'dataset.db';target.write_bytes(b'keep')
    with pytest.raises(ValueError,match='Target exists'): ingest(tmp_path,target)
    assert target.read_bytes()==b'keep'

def test_ai_migration_preserves_legacy_rows_and_scopes_them_out(tmp_path,monkeypatch):
    from sqlalchemy import create_engine,text,inspect
    from app.db import migrate
    path=tmp_path/'legacy.db'
    engine=create_engine('sqlite:///'+str(path))
    with engine.begin() as conn:
        conn.execute(text('''CREATE TABLE company_thresholds (id INTEGER PRIMARY KEY,company_id VARCHAR,metric VARCHAR,
            operator VARCHAR,warning_value FLOAT,critical_value FLOAT,department VARCHAR,active BOOLEAN,created_at DATETIME,updated_at DATETIME)'''))
        conn.execute(text("INSERT INTO company_thresholds(id,company_id,metric,operator,warning_value,critical_value,department,active) VALUES (1,'C','gross_margin_pct','less_than',30,20,'finance',1)"))
    monkeypatch.setattr(migrate,'engine',engine)
    migrate.migrate()
    with engine.connect() as conn:
        row=conn.execute(text('SELECT warning_value,tenant_id FROM company_thresholds WHERE id=1')).one()
        assert row==(30,'legacy-unscoped')
        assert conn.execute(text('SELECT version FROM ai_schema_version')).scalar()==2
    assert list(tmp_path.glob('*.backup-*.db'))
    engine.dispose()
