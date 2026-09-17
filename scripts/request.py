"""Trusted local CLI client. Never embed this secret or signing logic in a browser."""
import argparse
import json
import sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.core.config import get_settings
from app.api.security import signed_headers
parser=argparse.ArgumentParser()
parser.add_argument('method',choices=['GET','POST','PUT'])
parser.add_argument('path',help='Full API path including the encoded query string')
parser.add_argument('--body',default=None,help='JSON body')
parser.add_argument('--url',default='http://127.0.0.1:8001')
parser.add_argument('--tenant',default='11111111-1111-4111-8111-111111111111')
parser.add_argument('--company',default='22222222-2222-4222-8222-222222222222')
parser.add_argument('--actor',default='local-demo-finance')
args=parser.parse_args()
payload=json.loads(args.body) if args.body else None
req=httpx.Request(args.method,args.url+args.path,json=payload) if payload is not None else httpx.Request(args.method,args.url+args.path)
secret=get_settings().ai_service_internal_token
if not secret: raise SystemExit('Configure AI_SERVICE_INTERNAL_TOKEN first')
req.headers.update(signed_headers(secret,args.method,req.url.raw_path.decode(),req.read(),
    tenant_id=args.tenant,company_id=args.company,actor=args.actor,roles=['finance']))
with httpx.Client(timeout=90) as client:
    response=client.send(req)
print(response.status_code)
print(json.dumps(response.json(),ensure_ascii=False,indent=2))
