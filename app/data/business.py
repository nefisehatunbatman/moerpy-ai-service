"""Verified business CSV ingestion. Private/scenario labels never enter this database."""
import argparse
import csv
import hashlib
import json
import re
import sqlite3
from pathlib import Path

TABLES = ('companies','locations','master_products','sales_invoices','sales_invoice_lines','cost_history','inventory_snapshots','inventory_movements')
INDEXES = {
    'companies': ('company_id','tenant_id'), 'locations': ('company_id','location_id'),
    'master_products': ('company_id','product_id'), 'sales_invoices': ('company_id','invoice_date','invoice_id'),
    'sales_invoice_lines': ('company_id','invoice_id'), 'cost_history': ('company_id','effective_from','product_id'),
    'inventory_snapshots': ('company_id','snapshot_date','location_id','product_id'),
    'inventory_movements': ('company_id','event_date','movement_type'),
}

def ingest(source: Path, target: Path):
    source, target = source.resolve(), target.resolve()
    if target.exists():
        raise ValueError('Target exists; choose a new versioned DB path')
    manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('profile') != 'demo' or manifest.get('dataset_name') != 'moerpy_fictional_seafood_24m':
        raise ValueError('Expected the main demo business manifest, not card packs or private oracle')
    target.parent.mkdir(parents=True,exist_ok=True)
    temp = target.with_suffix('.building')
    if temp.exists():
        raise ValueError('Incomplete build exists; use a different target')
    counts, hashes = {}, {}
    conn = sqlite3.connect(temp)
    try:
        for table in TABLES:
            spec = manifest['tables'][table]
            columns = spec['columns']
            if not all(re.fullmatch('[a-z][a-z0-9_]*', c) for c in columns):
                raise ValueError('Invalid column name')
            conn.execute(f'CREATE TABLE {table} (' + ','.join('"'+c+'" TEXT' for c in columns) + ')')
            count = 0
            for part in spec['files']:
                path = (source/part['path']).resolve()
                if path.parent != source or not path.name.startswith(table+'-'):
                    raise ValueError('Invalid source path')
                with path.open('rb') as binary:
                    digest = hashlib.file_digest(binary,'sha256').hexdigest()
                if digest != part['sha256']:
                    raise ValueError(f'Checksum mismatch: {path.name}')
                hashes[path.name] = digest
                with path.open(encoding='utf-8-sig',newline='') as handle:
                    reader = csv.DictReader(handle)
                    if reader.fieldnames != columns:
                        raise ValueError(f'Column contract mismatch: {table}')
                    chunk, rows = [], 0
                    for row in reader:
                        if None in row or any(v is None for v in row.values()):
                            raise ValueError('Malformed CSV row')
                        if row.get('company_id') != manifest['company_id']:
                            raise ValueError('Foreign company in business source')
                        chunk.append(tuple(row[c] for c in columns)); rows += 1
                        if len(chunk) == 2000:
                            conn.executemany(f'INSERT INTO {table} VALUES ('+','.join('?' for _ in columns)+')',chunk); chunk=[]
                    if chunk:
                        conn.executemany(f'INSERT INTO {table} VALUES ('+','.join('?' for _ in columns)+')',chunk)
                    if rows != part['rows']:
                        raise ValueError('Manifest row count mismatch')
                    count += rows
            if count != spec['row_count']:
                raise ValueError('Table row count mismatch')
            counts[table] = count
            cols=','.join(INDEXES[table])
            conn.execute(f'CREATE INDEX idx_{table}_scope ON {table} ({cols})')
            conn.commit()
        conn.execute('CREATE UNIQUE INDEX invoice_id_unique ON sales_invoices(invoice_id)')
        conn.execute('CREATE UNIQUE INDEX line_id_unique ON sales_invoice_lines(invoice_line_id)')
        conn.execute('CREATE UNIQUE INDEX product_id_unique ON master_products(product_id)')
        conn.execute('CREATE UNIQUE INDEX location_id_unique ON locations(location_id)')
        tenant = conn.execute('SELECT tenant_id FROM companies WHERE company_id=?',(manifest['company_id'],)).fetchone()[0]
        for table in TABLES:
            if conn.execute(f'SELECT COUNT(*) FROM {table} WHERE tenant_id != ?', (tenant,)).fetchone()[0]:
                raise ValueError('Tenant mismatch')
        for sql in [
            'SELECT count(*) FROM sales_invoice_lines l LEFT JOIN sales_invoices i ON l.invoice_id=i.invoice_id WHERE i.invoice_id IS NULL',
            'SELECT count(*) FROM sales_invoice_lines l LEFT JOIN master_products p ON l.product_id=p.product_id WHERE p.product_id IS NULL',
            'SELECT count(*) FROM sales_invoices i LEFT JOIN locations l ON i.selling_location_id=l.location_id WHERE l.location_id IS NULL']:
            if conn.execute(sql).fetchone()[0]: raise ValueError('Unresolved canonical reference')
        metadata = {'dataset_id':manifest['dataset_id'],'date_range':manifest['date_range'],'company_id':manifest['company_id'],
            'tenant_id':tenant,'tables':counts,'source_rows':sum(t['row_count'] for t in manifest['tables'].values()),
            'imported_rows':sum(counts.values()),'source_sha256':hashes,'private_oracle_used':False,'schema_version':1}
        conn.execute('CREATE TABLE dataset_metadata (document TEXT NOT NULL)')
        conn.execute('INSERT INTO dataset_metadata VALUES (?)',(json.dumps(metadata),))
        conn.commit()
    finally:
        conn.close()
    temp.rename(target)
    return metadata

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--target',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(ingest(args.source,args.target),ensure_ascii=False,indent=2))
