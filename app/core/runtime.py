import logging
import math
import threading
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.requests import ClientDisconnect

from app.api.routes import v2
from app.api.security import authenticate
from app.core.config import get_settings
from app.core.errors import CompanyNotFoundError, InvalidPeriodError, InvalidSourceDataError
from app.core.logging import configure_logging
from app.db.base import init_db, engine
from app.data.factory import get_erp_provider
from app.decisions.service import DecisionNotFoundError, InvalidDecisionTransitionError
from app.llm.decision_generator import NumberGroundingError, LLMOutputValidationError
from app.llm.transport import ProviderError, ProviderRateLimitError, ProviderTimeoutError

settings = get_settings()
logger = logging.getLogger(__name__)
slots = threading.BoundedSemaphore(settings.max_concurrent_requests)
metrics = {'requests': 0, 'errors': 0, 'busy': 0, 'disconnected': 0, 'duration_seconds': 0.0}
metrics_lock = threading.Lock()


def validate_embedding_entry(entry, identity):
    vector = entry.embedding
    if (entry.embedding_model != identity or not isinstance(vector, list) or not vector
            or entry.embedding_dimensions != len(vector)
            or not all(type(v) in (int, float) and math.isfinite(v) for v in vector)
            or not any(v != 0 for v in vector)):
        logger.error('invalid_embedding_entry', extra={'entry_id': entry.id})
        raise RuntimeError('Embedding index mismatch: run scripts/reindex.py before serving requests')


@asynccontextmanager
async def lifespan(app):
    try:
        configure_logging()
        init_db()
        from app.db.base import SessionLocal
        from app.rag.knowledge_base import KnowledgeBaseRepository
        from app.rag.embeddings import get_embedding_provider
        with SessionLocal() as session:
            embedder = get_embedding_provider()
            kb = KnowledgeBaseRepository(session, embedder)
            kb.seed_if_empty()
            for entry in kb.list_all():
                validate_embedding_entry(entry, embedder.identity)
                if entry.company_id is None and (entry.company_contexts or entry.approval_count or entry.usage_count):
                    logger.error('legacy_global_learning', extra={'entry_id': entry.id})
                    raise RuntimeError('Legacy global learning needs isolation: run python -m app.db.migrate')
        yield
    finally:
        engine.dispose()


def error_response(status, detail, request_id, code=None, headers=None):
    body = {'detail': detail, 'request_id': request_id}
    if code:
        body['error_code'] = code
    return JSONResponse(status_code=status, content=body,
                        headers={**(headers or {}), 'X-Request-ID': request_id})


class ServiceBoundary:
    """Bound bodies before auth, replay via ASGI, hold slots until response completion."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = time.monotonic()
        request_id = uuid.uuid4().hex
        scope.setdefault('state', {})['request_id'] = request_id
        health_probe = scope['path'] in ('/health', '/ready')
        acquired = False
        response_started = False
        status = 500

        async def send_with_id(message):
            nonlocal status, response_started
            if message['type'] == 'http.response.start':
                response_started = True
                status = message['status']
                headers = [(k, v) for k, v in message.get('headers', []) if k.lower() != b'x-request-id']
                message = {**message, 'headers': headers + [(b'x-request-id', request_id.encode())]}
            await send(message)

        try:
            if not health_probe:
                acquired = slots.acquire(blocking=False)
                if not acquired:
                    with metrics_lock:
                        metrics['busy'] += 1
                    response = error_response(429, 'Service busy', request_id, headers={'Retry-After': '1'})
                    return await response(scope, receive, send_with_id)
            prefix = settings.ai_service_api_prefix
            if scope['path'] == prefix or scope['path'].startswith(prefix + '/'):
                length = dict(scope.get('headers', [])).get(b'content-length')
                if length is not None:
                    try:
                        declared_size = int(length)
                    except ValueError:
                        raise HTTPException(400, 'Invalid Content-Length') from None
                    if declared_size < 0:
                        raise HTTPException(400, 'Invalid Content-Length')
                    if declared_size > settings.max_request_bytes:
                        raise HTTPException(413, 'Request body too large')
                parts, size = [], 0
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        raise ClientDisconnect()
                    chunk = message.get('body', b'')
                    size += len(chunk)
                    if size > settings.max_request_bytes:
                        raise HTTPException(413, 'Request body too large')
                    parts.append(chunk)
                    if not message.get('more_body', False):
                        break
                body = b''.join(parts)

                def replay_body():
                    delivered = False

                    async def replay():
                        nonlocal delivered
                        if not delivered:
                            delivered = True
                            return {'type': 'http.request', 'body': body, 'more_body': False}
                        return await receive()
                    return replay

                await authenticate(Request(scope, replay_body()))
                await self.app(scope, replay_body(), send_with_id)
            else:
                await self.app(scope, receive, send_with_id)
        except ClientDisconnect:
            status = 499
            with metrics_lock:
                metrics['disconnected'] += 1
        except Exception as exc:
            if response_started:
                logger.exception('response_failed', extra={'request_id': request_id, 'error_type': type(exc).__name__})
                raise
            if isinstance(exc, HTTPException):
                response = error_response(exc.status_code, exc.detail, request_id, headers=exc.headers)
            elif isinstance(exc, (NumberGroundingError, LLMOutputValidationError)):
                response = error_response(422, 'Decision narrative failed verification', request_id, type(exc).__name__)
            elif isinstance(exc, InvalidDecisionTransitionError):
                response = error_response(409, 'Decision transition is not allowed', request_id, 'invalid_transition')
            elif isinstance(exc, (CompanyNotFoundError, DecisionNotFoundError)):
                response = error_response(404, 'Resource not found', request_id, 'not_found')
            elif isinstance(exc, InvalidPeriodError):
                response = error_response(422, 'Invalid request', request_id, 'invalid_request')
            elif isinstance(exc, InvalidSourceDataError):
                logger.warning('invalid_source_data', extra={'request_id': request_id, 'error_type': type(exc).__name__})
                response = error_response(422, 'Source data failed validation', request_id, 'invalid_source_data')
            elif isinstance(exc, ProviderRateLimitError):
                response = error_response(503, 'Model provider rate limited', request_id, 'provider_rate_limited', {'Retry-After': '60'})
            elif isinstance(exc, ProviderTimeoutError):
                response = error_response(504, 'Model provider timed out', request_id, 'provider_timeout')
            else:
                upstream = isinstance(exc, (httpx.HTTPError, ProviderError))
                code = 504 if isinstance(exc, httpx.TimeoutException) else 502 if upstream else 500
                logger.exception('request_failed', extra={'request_id': request_id, 'error_type': type(exc).__name__})
                response = error_response(code, 'Upstream unavailable' if upstream else 'Internal service error', request_id)
            await response(scope, receive, send_with_id)
        finally:
            elapsed = time.monotonic() - started
            if not health_probe:
                with metrics_lock:
                    metrics['requests'] += 1
                    metrics['duration_seconds'] += elapsed
                    if status >= 400 and status != 499:
                        metrics['errors'] += 1
            logger.info('request_completed', extra={'request_id': request_id, 'status': status, 'duration_seconds': round(elapsed, 4)})
            if acquired:
                slots.release()


app = FastAPI(title='MOERPY AI Service', version='2.0.0', lifespan=lifespan,
              docs_url='/docs' if settings.environment != 'production' else None,
              redoc_url='/redoc' if settings.environment != 'production' else None,
              openapi_url='/openapi.json' if settings.environment != 'production' else None)
app.add_middleware(ServiceBoundary)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Never echo input values, validator contexts or exception messages.
    return error_response(422, 'Invalid request', request.state.request_id, 'invalid_request')


@app.get('/health')
async def health():
    return {'status': 'ok'}


@app.get('/ready')
def ready(request: Request):
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        if not get_settings().ai_service_internal_token:
            raise RuntimeError('Authentication not configured')
        if not get_erp_provider().list_companies():
            raise RuntimeError('No companies available')
        return {'status': 'ready', 'erp_provider': get_settings().erp_provider}
    except Exception as exc:
        logger.exception('readiness_failed', extra={'request_id': request.state.request_id, 'error_type': type(exc).__name__})
        return JSONResponse(status_code=503, content={'status': 'not_ready'})


@app.get(settings.ai_service_api_prefix + '/metrics')
def service_metrics(request: Request):
    from app.api.security import require_role
    require_role(request.state.scope)
    with metrics_lock:
        return dict(metrics)


app.include_router(v2.router, prefix=settings.ai_service_api_prefix)

