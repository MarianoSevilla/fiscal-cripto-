"""Real Flask + active memory limiter; synthetic sessions and no external I/O."""
from datetime import datetime
import time

import pytest
from limits.storage import MemoryStorage

from app import app, db, limiter
from models import User


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    assert app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///')
    assert isinstance(limiter.storage, MemoryStorage)
    # Other regression modules disable the singleton limiter. This file runs
    # alone in a subprocess, and explicitly verifies the real limiter is active.
    app.config.update(TESTING=True, RATELIMIT_ENABLED=True, SESSION_COOKIE_SECURE=False)
    assert limiter.enabled
    limiter.reset()
    clock = [time.time()]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    with app.app_context():
        db.create_all()
    yield clock
    with app.app_context():
        db.session.remove()
        db.drop_all()
    limiter.reset()


def client_for(role='user', plan='free', suffix='one'):
    with app.app_context():
        user = User(
            email=f'{role}-{plan}-{suffix}@example.invalid',
            full_name='Persona sintética', nif='12345678Z', role=role,
            plan=plan, email_verified_at=datetime.utcnow(),
        )
        db.session.add(user)
        db.session.commit()
        identity, user_id = user.get_id(), user.id
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = identity
        session['_fresh'] = True
        now = int(time.time())
        session['auth_started_at'] = now
        session['auth_last_activity_at'] = now
    return client, user_id


def assert_me(client, authenticated=True, **kwargs):
    response = client.get('/api/me', **kwargs)
    assert response.status_code == 200, response.status_code
    assert response.headers['Cache-Control'] == 'no-store'
    if authenticated:
        assert response.json['user']['full_name'] == 'Persona sintética'
    else:
        assert response.json == {'user': None}
    return response.json['user']


@pytest.mark.parametrize('role,plan', [
    (role, plan) for role in ['user', 'fiscal_advisor', 'admin']
    for plan in ['free', 'pro']
])
def test_36_navigations_with_two_session_checks_and_server_role_gates(role, plan):
    client, _ = client_for(role, plan)
    routes = ['/dashboard', '/binance', '/modelo721', '/account']
    for navigation in range(36):
        assert client.get(routes[navigation % len(routes)]).status_code == 200
        # Legacy tool guards also check /api/me, in addition to the shared nav.
        for _ in range(2):
            user = assert_me(client)
            assert user['plan'] == plan
            assert user['is_admin'] == (role == 'admin')
            assert user['is_fiscal_advisor'] == (role != 'user')
    assert client.get('/api/admin/contactos').status_code == (200 if role == 'admin' else 403)
    assert client.get('/api/admin/asesoramiento/solicitudes').status_code == (403 if role == 'user' else 200)
    assert client.get('/admin/contactos').status_code == (200 if role == 'admin' else 302)


@pytest.mark.parametrize('authenticated', [False, True])
def test_old_hourly_and_daily_session_budgets_do_not_apply(isolated, authenticated):
    client = client_for()[0] if authenticated else app.test_client()
    # 180 checks within three minutes: above both old limits, below 120/minute.
    for _ in range(3):
        for _ in range(60):
            assert_me(client, authenticated)
        isolated[0] += 61


@pytest.mark.parametrize('authenticated', [False, True])
def test_session_endpoint_is_still_bounded_and_recovers(isolated, authenticated):
    client = client_for()[0] if authenticated else app.test_client()
    for _ in range(120):
        assert_me(client, authenticated)
    limited = client.get('/api/me')
    assert limited.status_code == 429
    assert 'user' not in limited.json
    assert limited.headers['Cache-Control'] == 'no-store'
    if authenticated:
        assert client.get('/dashboard').status_code == 200
    isolated[0] += 61
    assert_me(client, authenticated)


def test_authenticated_budget_follows_user_not_ip():
    client, _ = client_for()
    for _ in range(120):
        assert_me(client, environ_overrides={'REMOTE_ADDR': '192.0.2.10'})
    assert client.get('/api/me', environ_overrides={'REMOTE_ADDR': '192.0.2.11'}).status_code == 429
    other, _ = client_for(suffix='two')
    assert_me(other, environ_overrides={'REMOTE_ADDR': '192.0.2.10'})


def test_anonymous_budget_follows_ip_without_exposing_users():
    client_for()  # A private account exists; anonymous responses reveal none of it.
    client = app.test_client()
    for _ in range(120):
        assert_me(client, False, environ_overrides={'REMOTE_ADDR': '192.0.2.10'})
    assert app.test_client().get('/api/me', environ_overrides={'REMOTE_ADDR': '192.0.2.10'}).status_code == 429
    assert_me(client, False, environ_overrides={'REMOTE_ADDR': '192.0.2.11'})


@pytest.mark.parametrize('identity', [None, '123', 'v1:123:' + '0' * 64])
def test_anonymous_invalid_and_forged_sessions_never_reveal_profile(identity):
    client_for()
    client = app.test_client()
    if identity:
        with client.session_transaction() as session:
            session['_user_id'] = identity
            session['_fresh'] = True
    for _ in range(36):
        assert_me(client, False)
    assert client.get('/dashboard').status_code == 302
    assert client.get('/api/admin/contactos').status_code != 200
    for route in ['/api/analizar', '/api/721', '/api/721/xml']:
        assert client.post(route, json={}).status_code == 401


def test_expired_signed_session_remains_anonymous(isolated):
    client, _ = client_for()
    assert_me(client)
    isolated[0] += app.permanent_session_lifetime.total_seconds() + 1
    assert_me(client, False)
    assert client.get('/dashboard').status_code == 302
    assert client.get('/api/admin/contactos').status_code != 200


@pytest.mark.parametrize('change', ['disabled', 'credentials_rotated'])
def test_revoked_session_does_not_retain_access(change):
    client, user_id = client_for('admin')
    assert_me(client)
    with app.app_context():
        user = db.session.get(User, user_id)
        if change == 'disabled':
            user.is_active = False
        else:
            user.password_hash = 'synthetic-rotated-credential'
        db.session.commit()
    assert_me(client, False)
    assert client.get('/dashboard').status_code == 302
    assert client.get('/api/admin/contactos').status_code != 200


@pytest.mark.parametrize('route,allowed,status', [
    ('/api/login', 10, 401), ('/api/register', 5, 400),
])
def test_login_and_registration_keep_their_own_limits(route, allowed, status):
    client = app.test_client()
    for _ in range(36):
        assert_me(client, False)
    for _ in range(allowed):
        assert client.post(route, json={}).status_code == status
    assert client.post(route, json={}).status_code == 429
    assert_me(client, False)
    assert client.post(route, json={}).status_code == 429


@pytest.mark.parametrize('role', ['user', 'fiscal_advisor'])
@pytest.mark.parametrize('route,allowed', [
    ('/api/analizar', 3), ('/api/kucoin/analizar', 3),
    ('/api/bitget/analizar', 3), ('/api/721', 3), ('/api/721/xml', 10),
])
def test_fiscal_limits_still_apply_after_normal_navigation(role, route, allowed):
    client, _ = client_for(role)
    for _ in range(36):
        assert_me(client)
    # Missing files/data are rejected before any fiscal engine or provider runs.
    for _ in range(allowed):
        assert client.post(route, json={}).status_code == 400
    assert client.post(route, json={}).status_code == 429
    assert_me(client)


def test_existing_admin_fiscal_exemptions_are_unchanged():
    client, _ = client_for('admin')
    for route, count in [('/api/analizar', 4), ('/api/721', 4), ('/api/721/xml', 11)]:
        for _ in range(count):
            assert client.post(route, json={}).status_code == 400


def test_other_default_limits_are_not_relaxed():
    client = app.test_client()
    for _ in range(20):
        assert client.get('/verify-email-result').status_code == 200
    assert client.get('/verify-email-result').status_code == 429
    assert_me(client, False)
