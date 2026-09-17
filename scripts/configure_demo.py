"""Configure only AI-service for the verified large dataset; preserve provider credentials."""
import os
import secrets
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.chdir(ROOT)
from dotenv import dotenv_values
path=ROOT/'.env'
values=dotenv_values(path) if path.exists() else {}
token=values.get('AI_SERVICE_INTERNAL_TOKEN') or ''
if len(token)<32: token=secrets.token_urlsafe(48)
updates={'ERP_PROVIDER':'business','BUSINESS_DATASET_DB':'./data/business_24m.db',
    'AI_SERVICE_DATABASE_URL':'sqlite:///./data/service_v2.db','AI_SERVICE_INTERNAL_TOKEN':token,
    'ENVIRONMENT':'development','LLM_MODE':'offline','EMBEDDING_MODE':'local'}
lines=path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
result=[];written=set()
for line in lines:
    key=line.split('=',1)[0].strip()
    if key in updates:
        if key not in written: result.append(key+'='+updates[key]);written.add(key)
    else: result.append(line)
for key,value in updates.items():
    if key not in written: result.append(key+'='+value)
path.write_text('\n'.join(result)+'\n',encoding='utf-8')
os.environ.update(updates)
from app.db.base import init_db
from app.data.factory import get_erp_provider
init_db()
provider=get_erp_provider()
print('AI service configured: business_24m, offline narrative, local embeddings, signed API context required.')
print('Provider credentials preserved. Internal secret was not printed.')
print(f'Indexed rows: {provider.metadata["imported_rows"]}; companies: {len(provider.list_companies())}')
