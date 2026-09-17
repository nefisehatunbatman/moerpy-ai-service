"""Regressions for authorization, safe errors, ASGI boundaries and data contracts."""
import asyncio
import json
import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from app.core.config import Settings, SERVICE_ROOT
from app.core.errors import InvalidPeriodError, InvalidSourceDataError
from app.data.models import Company, CostFact, SalesFact, WasteReturnFact, Period
from app.data.providers.fake_provider import FakeERPDataProvider

FEB = Period(date(2026, 2, 1), date(2026, 2, 28))
ANALYSIS = dict(company_id='COMP-001', period_start=str(FEB.start), period_end=str(FEB.end))


def test_reader_cannot_write_or_call_generator(client, monkeypatch):
    from app.api.routes import v2
    anomaly = client.post('/api/v1/analysis/run', json=ANALYSIS).json()[0]
    client.roles = ['user']
    def forbidden(*args, **kwargs):
        pytest.fail('Reader reached a write or paid operation')
    monkeypatch.setattr(v2, 'compute_kpis', forbidden)
    monkeypatch.setattr(v2, 'generate_decision_for_anomaly', forbidden)
    assert client.post('/api/v1/analysis/run', json=ANALYSIS).status_code == 403
    assert client.post(f"/api/v1/anomalies/{anomaly['id']}/generate-decision").status_code == 403
    assert client.get('/api/v1/companies/COMP-001/anomalies').status_code == 200


@pytest.mark.parametrize('error', [KeyError, IndexError, ValueError, RuntimeError])
def test_programming_errors_are_500_and_log_stack_without_payload(client, monkeypatch, caplog, error):
    from app.api.routes import v2
    from app.core.logging import JsonFormatter
    def broken(*args):
        raise error('private-password-and-source-data')
    monkeypatch.setattr(v2, 'compute_kpis', broken)
    with caplog.at_level(logging.ERROR):
        response = client.post('/api/v1/analysis/run', json=ANALYSIS)
    assert response.status_code == 500
    assert response.headers['x-request-id'] == response.json()['request_id']
    assert 'private-password' not in response.text
    record = next(r for r in caplog.records if r.getMessage() == 'request_failed')
    formatted = JsonFormatter().format(record)
    assert 'private-password' not in formatted
    assert any(f['function'] == 'broken' for f in json.loads(formatted)['traceback'])


def test_domain_error_is_safe_422(client, monkeypatch):
    from app.api.routes import v2
    def invalid(*args):
        raise InvalidSourceDataError('private source row')
    monkeypatch.setattr(v2, 'compute_kpis', invalid)
    response = client.post('/api/v1/analysis/run', json=ANALYSIS)
    assert response.status_code == 422
    assert response.json()['error_code'] == 'invalid_source_data'
    assert 'private source row' not in response.text
    assert response.headers['x-request-id']


def test_period_errors_have_one_contract(client):
    params = dict(period_start='2026-02-28', period_end='2026-02-01')
    responses = [client.get('/api/v1/companies/COMP-001/kpis', params=params),
                 client.post('/api/v1/analysis/run', json={'company_id': 'COMP-001', **params})]
    for response in responses:
        assert response.status_code == 422
        assert response.json()['detail'] == 'Invalid request'
        assert response.json()['error_code'] == 'invalid_request'
        assert response.headers['x-request-id'] == response.json()['request_id']


def test_probes_bypass_saturated_slots(client, monkeypatch):
    from app.core import runtime
    semaphore = threading.BoundedSemaphore(1)
    semaphore.acquire()
    monkeypatch.setattr(runtime, 'slots', semaphore)
    assert client.get('/health').status_code == 200
    assert client.get('/ready').status_code == 200
    busy = client.get('/api/v1/companies/COMP-001/anomalies')
    assert busy.status_code == 429 and busy.headers['retry-after'] == '1'
    assert not semaphore.acquire(blocking=False)
    semaphore.release()


def test_readiness_logs_failure_without_disclosing_it(client, monkeypatch, caplog):
    from app.core import runtime
    def unavailable():
        raise RuntimeError('secret database URL')
    monkeypatch.setattr(runtime, 'get_erp_provider', unavailable)
    with caplog.at_level(logging.ERROR):
        response = client.get('/ready')
    assert response.status_code == 503
    assert 'secret database' not in response.text
    assert response.headers['x-request-id']
    assert any(r.getMessage() == 'readiness_failed' and r.exc_info for r in caplog.records)


@pytest.mark.parametrize('vector', [None, [], [float('nan')], [float('inf')], ['bad'], [0.0]])
def test_bad_embedding_has_controlled_diagnostic(vector, caplog):
    from app.core.runtime import validate_embedding_entry
    entry = SimpleNamespace(id='broken-entry', embedding=vector, embedding_model='model', embedding_dimensions=1)
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match='Embedding index mismatch'):
        validate_embedding_entry(entry, 'model')
    assert any(getattr(r, 'entry_id', '') == 'broken-entry' for r in caplog.records)


@pytest.mark.asyncio
async def test_engine_disposed_on_failed_startup(monkeypatch):
    from app.core import runtime
    disposed = []
    monkeypatch.setattr(runtime, 'configure_logging', lambda: None)
    monkeypatch.setattr(runtime, 'engine', SimpleNamespace(dispose=lambda: disposed.append(True)))
    def failed():
        raise RuntimeError('startup failed')
    monkeypatch.setattr(runtime, 'init_db', failed)
    with pytest.raises(RuntimeError):
        async with runtime.lifespan(runtime.app):
            pytest.fail('Startup should fail')
    assert disposed == [True]


def test_turkish_business_date_at_utc_day_boundary(monkeypatch):
    from app.core import dates
    from app.api.routes.v2 import validated_period
    class FixedDateTime:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(dates, 'datetime', FixedDateTime)
    monkeypatch.setattr(dates, 'get_settings', lambda: SimpleNamespace(reporting_timezone='Europe/Istanbul'))
    assert dates.reporting_today() == date(2026, 9, 15)
    assert validated_period(date(2026, 9, 1), date(2026, 9, 15)).end == date(2026, 9, 15)
    with pytest.raises(InvalidPeriodError):
        validated_period(date(2026, 9, 1), date(2026, 9, 16))


def config(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_paths_are_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = config(ai_service_database_url='sqlite:///./data/a.db', business_dataset_db='./data/business.db')
    assert Path(make_url(settings.ai_service_database_url).database) == SERVICE_ROOT / 'data/a.db'
    assert Path(settings.business_dataset_db) == SERVICE_ROOT / 'data/business.db'
    assert Settings.model_config['env_file'] == SERVICE_ROOT / '.env'


def test_same_business_and_state_file_is_rejected():
    with pytest.raises(ValueError, match='separate'):
        config(ai_service_database_url='sqlite:///./data/../data/business.db', business_dataset_db='./data/business.db')


def test_loopback_aliases_cannot_bypass_database_separation():
    with pytest.raises(ValueError, match='separate'):
        config(erp_provider='postgres', erp_database_url='postgresql://reader:secret@LOCALHOST/source',
               ai_service_database_url='postgresql+psycopg://writer:secret@127.0.0.1:5432/source')


@pytest.mark.parametrize('url', ['sqlite+pysqlite://', 'sqlite:///file::memory:?uri=true',
                               'sqlite:///file:shared?mode=memory&cache=shared&uri=true'])
def test_all_memory_database_forms_rejected_in_production(url):
    with pytest.raises(ValueError, match='persistent'):
        config(environment='production', erp_provider='business', ai_service_database_url=url,
               ai_service_internal_token='x' * 40)


def test_invalid_database_url_does_not_echo_credentials():
    with pytest.raises(ValueError) as error:
        config(ai_service_database_url='not-a-url-with-secret-password')
    assert 'Invalid database URL' in str(error.value)
    assert 'secret-password' not in str(error.value)


def test_no_fixture_tenant_default_in_source_contracts():
    with pytest.raises(TypeError):
        Company('company', 'name', 'TRY')
    with pytest.raises(TypeError):
        SalesFact('sale', 'company', 'store', 'product', FEB, 1, 100, 0, 10)
    with pytest.raises(InvalidSourceDataError):
        Company('company', 'name', 'TRY', '')


def test_bad_cost_range_and_event_type_are_rejected():
    with pytest.raises(InvalidSourceDataError):
        CostFact('cost', 'c', 'p', FEB, 10, 'TRY', 's', tenant_id='t',
                 effective_date=FEB.end, effective_to=FEB.start)
    with pytest.raises(InvalidSourceDataError):
        WasteReturnFact('w', 'c', 's', 'p', FEB.end, 'Waste', 1, 'reason', tenant_id='t')


def test_fixture_parser_preserves_cost_availability_and_lineage():
    row = dict(id='s', company_id='c', store_id='s', product_id='p', period_start=str(FEB.start),
               period_end=str(FEB.end), quantity_sold=1, revenue=100, discount=0, unit_cost=None,
               tenant_id='tenant-real', import_batch_id='batch', source_system='source', variant_id='variant',
               sales_date='2026-02-15', cogs_amount=0, cost_basis_known=False)
    fact = FakeERPDataProvider._parse_sales_fact(row)
    assert fact.tenant_id == 'tenant-real' and fact.import_batch_id == 'batch'
    assert fact.source_system == 'source' and fact.variant_id == 'variant'
    assert fact.sales_date == date(2026, 2, 15) and fact.cogs_amount == 0
    assert fact.cost_basis_known is False


def http_scope(path='/stream', headers=()):
    return dict(type='http', method='GET', path=path, raw_path=path.encode(), query_string=b'',
                headers=list(headers), scheme='http', server=('test', 80), client=('test', 1), http_version='1.1')


@pytest.mark.asyncio
async def test_stream_holds_slot_until_final_body(monkeypatch):
    from app.core import runtime
    semaphore = threading.BoundedSemaphore(1)
    monkeypatch.setattr(runtime, 'slots', semaphore)
    body_started, finish = asyncio.Event(), asyncio.Event()
    async def stream(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'first', 'more_body': True})
        body_started.set()
        await finish.wait()
        await send({'type': 'http.response.body', 'body': b'last', 'more_body': False})
    async def receive():
        return {'type': 'http.request', 'body': b''}
    messages = []
    async def send(message):
        messages.append(message)
    task = asyncio.create_task(runtime.ServiceBoundary(stream)(http_scope(), receive, send))
    try:
        await asyncio.wait_for(body_started.wait(), 2)
        assert not semaphore.acquire(blocking=False)
    finally:
        finish.set()
        await asyncio.wait_for(task, 2)
    assert semaphore.acquire(blocking=False)
    semaphore.release()
    assert b'x-request-id' in dict(messages[0]['headers'])


@pytest.mark.asyncio
async def test_oversized_content_length_rejected_before_body_read():
    from app.core import runtime
    async def forbidden(*args):
        pytest.fail('Oversized request reached body or application')
    messages = []
    async def send(message):
        messages.append(message)
    scope = http_scope('/api/v1/analysis/run', [(b'content-length', b'99999999')])
    await runtime.ServiceBoundary(forbidden)(scope, forbidden, send)
    assert messages[0]['status'] == 413
