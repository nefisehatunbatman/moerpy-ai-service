"""Signed service-to-service context. Shared token alone never authorizes a company."""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from fastapi import Request, HTTPException
from app.core.config import get_settings

@dataclass(frozen=True)
class Scope:
    tenant_id: str
    company_id: str
    actor: str
    roles: tuple[str,...]

def signed_headers(secret,method,path,body,*,tenant_id,company_id,actor,roles,timestamp=None):
    payload=dict(tenant_id=tenant_id,company_id=company_id,actor=actor,roles=roles,
        ts=int(time.time()) if timestamp is None else timestamp,method=method.upper(),path=path,body_sha256=hashlib.sha256(body).hexdigest())
    context=base64.urlsafe_b64encode(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).decode()
    return {'X-Internal-Token':secret,'X-AI-Context':context,
            'X-AI-Signature':hmac.new(secret.encode(),context.encode(),hashlib.sha256).hexdigest()}

async def authenticate(request: Request):
    secret=get_settings().ai_service_internal_token
    if not secret:
        raise HTTPException(503,'Service authentication is not configured')
    token=request.headers.get('X-Internal-Token','')
    context=request.headers.get('X-AI-Context','')
    signature=request.headers.get('X-AI-Signature','')
    if len(context)>4096 or not hmac.compare_digest(token.encode(),secret.encode()) or not hmac.compare_digest(signature.encode(),hmac.new(secret.encode(),context.encode(),hashlib.sha256).hexdigest().encode()):
        raise HTTPException(401,'Invalid service authentication')
    try:
        p=json.loads(base64.urlsafe_b64decode(context))
        if not isinstance(p,dict) or type(p.get('ts')) is not int: raise ValueError()
        if abs(time.time()-p['ts'])>get_settings().context_max_age_seconds: raise ValueError()
        path=request.scope.get('raw_path',request.url.path.encode()).decode()+('?' + request.url.query if request.url.query else '')
        if p['method']!=request.method or p['path']!=path: raise ValueError()
        if p['body_sha256']!=hashlib.sha256(await request.body()).hexdigest(): raise ValueError()
        if any(not isinstance(p[k],str) or not p[k] or len(p[k])>200 for k in ('tenant_id','company_id','actor')): raise ValueError()
        if not isinstance(p['roles'],list) or not all(isinstance(r,str) for r in p['roles']): raise ValueError()
        request.state.scope=Scope(p['tenant_id'],p['company_id'],p['actor'],tuple(p['roles']))
    except (ValueError,KeyError,TypeError,OverflowError):
        raise HTTPException(401,'Invalid signed context')
    return request.state.scope

def scope_for(request: Request):
    return request.state.scope

def require_company(scope,company_id,provider):
    if scope.company_id!=company_id:
        raise HTTPException(404,'Company not found')
    company=provider.get_company(company_id)
    if not company or scope.company_id!=company_id or scope.tenant_id!=company.tenant_id:
        raise HTTPException(404,'Company not found')
    return company

def require_record(scope,record):
    if record is None or record.company_id!=scope.company_id or record.tenant_id!=scope.tenant_id:
        raise HTTPException(404,'Record not found')
    return record

def require_role(scope):
    if not set(scope.roles)&{'admin','owner','executive','finance'}:
        raise HTTPException(403,'Finance approval permission required')
