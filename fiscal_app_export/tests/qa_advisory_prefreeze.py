"""Real Flask/U03 ORM tests; run only via isolated SQLite or PostgreSQL runners."""
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest
from sqlalchemy import event, inspect
from werkzeug.exceptions import ServiceUnavailable

import app as module
from app import app, db
from models import User, FiscalAdvisoryRequest
from advisory_prefreeze import SUSPENSION_MESSAGE

PUBLIC = [
    ('POST', '/api/pago/iniciar/synthetic-link', {}),
    ('GET', '/api/pago/paypal/capture?request_id=1&token=synthetic-order', None),
    ('POST', '/api/webhooks/paypal', {'event_type': 'PAYMENT.CAPTURE.COMPLETED', 'resource': {'id': 'synthetic-capture', 'custom_id': '1'}}),
    ('POST', '/api/webhooks/paypal', {'event_type': 'PAYMENT.CAPTURE.REFUNDED', 'resource': {'id': 'synthetic-capture'}}),
    ('POST', '/api/webhooks/stripe', {'type': 'checkout.session.completed', 'data': {'object': {'id': 'synthetic-session', 'amount_total': 4900}}}),
    ('GET', '/api/pago/info/synthetic-link', None),
]
ADMIN = [
    ('POST', '/api/admin/asesoramiento/solicitudes/1/enviar-presupuesto', {'amount_euros': 999}),
    ('POST', '/api/admin/asesoramiento/solicitudes/1/estado', {'status': 'refunded'}),
    ('DELETE', '/api/admin/asesoramiento/solicitudes/1', None),
    ('POST', '/api/admin/asesoramiento/solicitudes/1/mensaje', {'mensaje': 'Synthetic', 'set_pendiente_info': True}),
    ('POST', '/api/admin/asesoramiento/solicitudes/1/mensaje', {'mensaje': 'Synthetic', 'set_pendiente_info': False}),
    ('POST', '/api/admin/asesoramiento/solicitudes/1/nota', {'nota': 'Synthetic'}),
    ('POST', '/api/admin/asesoramiento/solicitudes/1/is-test', {'is_test': True}),
    ('POST', '/api/asesoramiento/files/1', None),
]
FINANCIAL_TABLES = ('fiscal_advisory_requests', 'fiscal_advisory_files',
                    'fiscal_advisory_status_history', 'advisory_internal_notes', 'advisory_audit_log')


@pytest.fixture(scope='module', autouse=True)
def setup():
    assert app.config['TESTING'] is False
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False, SESSION_COOKIE_SECURE=False)
    with app.app_context():
        assert db.engine.url.database.endswith(('prefreeze.sqlite', 'prefreeze_ci'))
        db.create_all()
        db.session.add_all([User(id=i, email=f'fixture{i}@example.invalid', role=role,
                                is_active=True, email_verified_at=datetime(2025, 1, 1))
                            for i, role in enumerate(['admin', 'fiscal_advisor', 'user'], 1)])
        db.session.add(FiscalAdvisoryRequest(id=1, user_id=3, full_name='Synthetic Client',
            email='client@example.invalid', tax_residence_country='España', tax_year=2025,
            service_type='revision_basica', case_description='Synthetic case description',
            status='quote_sent', quoted_amount=4900, payment_link_token='synthetic-link',
            paypal_order_id='synthetic-order', paypal_capture_id='synthetic-capture',
            stripe_checkout_session_id='synthetic-session'))
        db.session.commit()
    yield
    with app.app_context():
        db.session.remove()
        db.drop_all()


def client(uid=None):
    cli = app.test_client()
    if uid:
        with cli.session_transaction() as sess:
            sess['_user_id'] = str(uid)
            sess['_fresh'] = True
    return cli


def snapshot():
    with app.app_context(), db.engine.connect() as conn:
        return {name: tuple(tuple(row) for row in conn.execute(db.metadata.tables[name].select()))
                for name in FINANCIAL_TABLES}


@pytest.fixture
def no_effects():
    before = snapshot()
    def forbidden(*args, **kwargs):
        raise AssertionError('PREFREEZE must not call a provider or send email')
    def no_dml(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in ('INSERT', 'UPDATE', 'DELETE'):
            assert not any(name in statement.lower() for name in FINANCIAL_TABLES), statement
    with app.app_context():
        engine = db.engine
    event.listen(engine, 'before_cursor_execute', no_dml)
    try:
        with patch('requests.sessions.Session.request', forbidden), patch('resend.Emails.send', forbidden), \
             patch.object(module, '_paypal_create_order', forbidden), \
             patch.object(module, '_paypal_capture_order', forbidden), \
             patch.object(module, '_paypal_get_access_token', forbidden), \
             patch.object(module, '_on_payment_completed', forbidden):
            yield
    finally:
        event.remove(engine, 'before_cursor_execute', no_dml)
    assert snapshot() == before


def suspended(response, html=False):
    assert response.status_code == 503
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Retry-After'] == '300'
    if html:
        assert SUSPENSION_MESSAGE in response.get_data(as_text=True)
    else:
        assert response.get_json()["error"] == SUSPENSION_MESSAGE
    if not html:
        assert response.get_json()['state'] == 'reconciliation_pending'
        assert 'ok' not in response.get_json()
        assert 'redirect_url' not in response.get_json()
    assert 'synthetic-order' not in response.get_data(as_text=True)
    assert 'client@example.invalid' not in response.get_data(as_text=True)


@pytest.mark.parametrize('operation', PUBLIC + ADMIN)
@pytest.mark.parametrize('configured', [False, True])
def test_routes_block_before_effects(operation, configured, no_effects):
    method, url, payload = operation
    with patch.object(module, '_PAYPAL_ENABLED', configured), \
         patch.object(module, '_stripe_available', configured), \
         patch.object(module, '_STRIPE_SECRET_KEY', 'fictional' if configured else ''), \
         patch.object(module, '_ADVISORY_UPLOADS_ENABLED', True):
        suspended(client(1).open(url, method=method, json=payload), '/capture' in url)


@pytest.mark.parametrize('url', ['/api/webhooks/paypal', '/api/webhooks/stripe'])
@pytest.mark.parametrize('payload', [b'', b'not-json', b'{}'])
def test_webhooks_never_ack_or_parse_untrusted_payload(url, payload, no_effects):
    for _ in range(3):
        suspended(client().post(url, data=payload, content_type='application/json'))


@pytest.mark.parametrize('operation', ADMIN)
def test_auth_is_preserved(operation, no_effects):
    method, url, data = operation
    assert client().open(url, method=method, json=data).status_code == 401
    if '/files/' not in url:
        assert client(3).open(url, method=method, json=data).status_code == 403
    if method == 'DELETE' or url.endswith('/is-test'):
        assert client(2).open(url, method=method, json=data).status_code == 403


@pytest.mark.parametrize('status', list(FiscalAdvisoryRequest.STATUS_LABELS))
def test_status_never_changes_or_invites_repayment(status, no_effects):
    # Each requested target status is denied before loading the request.
    suspended(client(1).post('/api/admin/asesoramiento/solicitudes/1/estado', json={'status': status}))


def test_concurrent_requests_do_not_mutate_or_call_provider(no_effects):
    operations = (PUBLIC + ADMIN) * 4
    def batch(group):
        barrier = Barrier(len(group))
        def invoke(operation):
            cli = client(1)
            barrier.wait(timeout=15)
            method, url, data = operation
            response = cli.open(url, method=method, json=data)
            suspended(response, '/capture' in url)
            return response.status_code
        with ThreadPoolExecutor(max_workers=len(group)) as executor:
            return list(executor.map(invoke, group))
    with patch.object(module, '_PAYPAL_ENABLED', True), \
         patch.object(module, '_stripe_available', True), \
         patch.object(module, '_STRIPE_SECRET_KEY', 'fictional'):
        results = batch(operations[:28]) + batch(operations[28:])
    assert results == [503] * 56


@pytest.mark.parametrize('helper,args', [('_paypal_get_access_token', ()),
    ('_paypal_create_order', (None,)), ('_paypal_capture_order', ('synthetic-order',)),
    ('_on_payment_completed', (None, 4900, 'EUR', 'paypal', 'synthetic'))])
def test_direct_helpers_fail_before_io_or_mutation(helper, args):
    with patch('requests.sessions.Session.request', side_effect=AssertionError('external I/O')):
        with pytest.raises(ServiceUnavailable):
            getattr(module, helper)(*args)


def test_read_only_queries_and_public_pages_remain_available(no_effects):
    for url in ('/api/admin/asesoramiento/solicitudes', '/api/admin/asesoramiento/solicitudes/1',
                '/api/me', '/api/stats-v2/encuentro'):
        assert client(1).get(url).status_code == 200
    assert client(3).get('/api/asesoramiento/mis-solicitudes').status_code == 200
    for url in ('/', '/login/', '/signup/', '/como-funciona', '/modelo721', '/faq', '/pagar/synthetic-link'):
        response = client().get(url, follow_redirects=True)
        assert response.status_code == 200, url
    response = client().get('/pagar/synthetic-link?cancelado=1&error=capture_failed')
    assert SUSPENSION_MESSAGE in response.get_data(as_text=True)
    assert '<button' not in response.get_data(as_text=True)
    assert 'iniciarPago' not in response.get_data(as_text=True)


def test_no_financial_off_switch_and_no_schema_extension():
    # No config/env branch in the always-denying implementation.
    source = Path(module.__file__).with_name('advisory_prefreeze.py').read_text()
    assert 'os.environ' not in source and 'app.config' not in source
    with app.app_context():
        assert 'paypal_payment_attempts' not in inspect(db.engine).get_table_names()
    tree = ast.parse(Path(module.__file__).read_text())
    names = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    guarded = {n.name for n in names.values() if any(isinstance(d, ast.Call)
               and isinstance(d.func, ast.Name) and d.func.id == 'advisory_financial_prefreeze'
               for d in n.decorator_list)}
    assert guarded == {'advisory_enviar_presupuesto', 'advisory_enviar_mensaje', 'pago_info',
        'pago_iniciar', 'pago_paypal_capture', 'paypal_webhook', 'stripe_webhook',
        'advisory_upload_file', 'admin_advisory_change_status', 'admin_advisory_set_is_test',
        'admin_advisory_add_note', 'admin_advisory_delete'}


@pytest.mark.parametrize('query', ['', '?request_id=invalid', '?request_id=999999&token=unknown',
    '?request_id=1&token=synthetic-order&PayerID=synthetic-payer'])
def test_capture_never_uses_return_arguments(query, no_effects):
    suspended(client().get('/api/pago/paypal/capture' + query), html=True)


def test_denied_routes_do_not_even_load_financial_records(no_effects):
    def no_financial_sql(conn, cursor, statement, parameters, context, executemany):
        assert not any(name in statement.lower() for name in FINANCIAL_TABLES)
    with app.app_context():
        engine = db.engine
    event.listen(engine, 'before_cursor_execute', no_financial_sql)
    try:
        for method, url, data in PUBLIC + ADMIN:
            suspended(client(1).open(url, method=method, json=data), '/capture' in url)
    finally:
        event.remove(engine, 'before_cursor_execute', no_financial_sql)
