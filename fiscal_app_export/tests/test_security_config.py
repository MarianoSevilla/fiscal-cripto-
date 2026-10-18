"""U02: synthetic configuration matrix and real HTTP cookies, never production.

Pure policy tests do not import app.py. Full-app checks run in fresh subprocesses
with an explicit environment, temporary SQLite and socket/DNS access blocked.
"""
from http.cookies import SimpleCookie
import os
from pathlib import Path
import subprocess
import sys

from flask import Flask, session
from flask_login import LoginManager, UserMixin, current_user, login_user
import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
from security_config import DEVELOPMENT_SECRET, build_security_config

FAKE_SECRET = "U02-FICTITIOUS-SESSION-KEY-NOT-FOR-REAL-USE-123"
MARKERS = (
    "RAILWAY_ENVIRONMENT_ID", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID", "RAILWAY_DEPLOYMENT_ID", "RAILWAY_PUBLIC_DOMAIN",
    "RAILWAY_PRIVATE_DOMAIN", "PORT", "SERVER_SOFTWARE",
)


@pytest.mark.parametrize("mode", [None, "", "production", "PRODUCTION", "Production", " production ", "staging"])
def test_secure_default_with_unchanged_key(mode):
    env = {"SECRET_KEY": FAKE_SECRET}
    if mode is not None:
        env["FLASK_ENV"] = mode
    config = build_security_config(env)
    assert config["SECRET_KEY"] == FAKE_SECRET
    assert config["SESSION_COOKIE_SECURE"] is True
    assert config["REMEMBER_COOKIE_SECURE"] is True
    assert config["DEBUG"] is False
    assert config["TESTING"] is False


@pytest.mark.parametrize("mode", [None, "production", "PRODUCTION", "staging"])
@pytest.mark.parametrize("key", [None, "", " \t\n", DEVELOPMENT_SECRET, " " + DEVELOPMENT_SECRET + " "])
def test_secure_modes_reject_missing_blank_or_development_key(mode, key):
    env = {"RAILWAY_SERVICE_ID": "fictitious-service"}
    if mode is not None:
        env["FLASK_ENV"] = mode
    if key is not None:
        env["SECRET_KEY"] = key
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        build_security_config(env)


@pytest.mark.parametrize("mode", ["prod", "produciton", "unknown", "test", "dev"])
def test_unknown_mode_never_falls_back(mode):
    with pytest.raises(RuntimeError, match="Unsupported FLASK_ENV") as error:
        build_security_config({"FLASK_ENV": mode, "SECRET_KEY": FAKE_SECRET})
    assert mode not in str(error.value)
    assert FAKE_SECRET not in str(error.value)


@pytest.mark.parametrize("mode", ["development", "testing", "DEVELOPMENT", " Testing "])
def test_explicit_local_exception(mode):
    with pytest.warns(UserWarning, match="explicit local"):
        config = build_security_config({"FLASK_ENV": mode})
    assert config["SECRET_KEY"] == DEVELOPMENT_SECRET
    assert config["SESSION_COOKIE_SECURE"] is False
    assert config["REMEMBER_COOKIE_SECURE"] is False
    for prefix in ("SESSION", "REMEMBER"):
        assert config[prefix + "_COOKIE_HTTPONLY"] is True
        assert config[prefix + "_COOKIE_SAMESITE"] == "Lax"


@pytest.mark.parametrize("mode", ["development", "testing"])
@pytest.mark.parametrize("marker", MARKERS)
@pytest.mark.parametrize("value", ["fictitious-deployment", ""])
def test_deployed_service_cannot_claim_local_exception(mode, marker, value):
    with pytest.raises(RuntimeError, match="forbidden in a deployed service"):
        build_security_config({"FLASK_ENV": mode, marker: value, "SECRET_KEY": FAKE_SECRET})


@pytest.mark.parametrize("flag", ["1", "true", "yes", "TRUE", "off", " false ", "unexpected"])
def test_secure_mode_rejects_cli_debug_override(flag):
    with pytest.raises(RuntimeError, match="FLASK_DEBUG"):
        build_security_config({"SECRET_KEY": FAKE_SECRET, "FLASK_DEBUG": flag})


@pytest.mark.parametrize("flag", ["", "0", "false", "FALSE", "no"])
def test_secure_mode_accepts_flask_cli_false_flags(flag):
    assert build_security_config({"SECRET_KEY": FAKE_SECRET, "FLASK_DEBUG": flag})["DEBUG"] is False


def test_validation_does_not_trim_or_rotate_supplied_key():
    supplied = " " + FAKE_SECRET + " "
    assert build_security_config({"SECRET_KEY": supplied})["SECRET_KEY"] == supplied


@pytest.mark.parametrize("mode,secure", [("production", True), ("staging", True), ("development", False), ("testing", False)])
def test_real_session_and_remember_headers_and_restoration(mode, secure, monkeypatch):
    # Flask/Flask-Login emit the cookies; there is no mocked Set-Cookie header.
    monkeypatch.setattr("socket.socket.connect", lambda *args: pytest.fail("Network forbidden"))
    app = Flask("u02-cookie-fixture")
    app.config.update(build_security_config({"FLASK_ENV": mode, "SECRET_KEY": FAKE_SECRET}))
    manager = LoginManager(app)
    user = UserMixin()
    user.id = "702"
    manager.user_loader(lambda user_id: user if user_id == user.id else None)

    @app.get("/login")
    def login_fixture():
        login_user(user, remember=True)
        session["fixture"] = "fictitious-value"
        return "ok"

    @app.get("/identity")
    def identity():
        return str(current_user.get_id())

    client = app.test_client()
    response = client.get("/login", base_url="https://fixture.example.invalid")
    cookies = SimpleCookie()
    for header in response.headers.getlist("Set-Cookie"):
        cookies.load(header)
    assert {"session", "remember_token"} <= set(cookies)
    for name in ("session", "remember_token"):
        assert bool(cookies[name]["secure"]) is secure
        assert bool(cookies[name]["httponly"]) is True
        assert cookies[name]["samesite"] == "Lax"
    assert client.get("/identity", base_url="https://fixture.example.invalid").data == b"702"
    client.delete_cookie("session", domain="fixture.example.invalid")
    assert client.get("/identity", base_url="https://fixture.example.invalid").data == b"702"


_NETWORK_GUARD = """
import socket
def forbidden(*args, **kwargs):
    raise AssertionError('U02 subprocess forbids network and DNS')
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.getaddrinfo = forbidden
"""


def _run_app(tmp_path, env, script):
    # NO os.environ.copy(): inherited DATABASE_URL and credentials cannot escape.
    controlled = {
        "PATH": os.defpath,
        "FLASK_ENV": "production",
        "SECRET_KEY": FAKE_SECRET,
        "DATABASE_URL": "sqlite:///" + str(tmp_path / "fixture.sqlite"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLCONFIGDIR": str(tmp_path / "mpl"),
        "RESEND_API_KEY": "",
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
        "PAYPAL_CLIENT_ID": "",
        "PAYPAL_CLIENT_SECRET": "",
        "STRIPE_SECRET_KEY": "",
        "STRIPE_WEBHOOK_SECRET": "",
        "ADMIN_EMAILS": "",
        "FISCAL_ADVISOR_EMAILS": "",
        "PROCESSING_ERROR_EMAILS_ENABLED": "false",
    }
    controlled.update(env)
    controlled = {key: value for key, value in controlled.items() if value is not None}
    result = subprocess.run(
        [sys.executable, "-c", _NETWORK_GUARD + script],
        cwd=APP_DIR, env=controlled, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("env", [
    {"SECRET_KEY": None}, {"SECRET_KEY": ""}, {"SECRET_KEY": " \t"},
    {"SECRET_KEY": DEVELOPMENT_SECRET}, {"FLASK_ENV": "unexpected"},
    {"FLASK_ENV": None, "RAILWAY_SERVICE_ID": "fixture", "SECRET_KEY": None},
    {"FLASK_ENV": "testing", "RAILWAY_SERVICE_ID": "fixture"},
    {"FLASK_DEBUG": "1"},
])
def test_full_app_rejects_bad_config_before_database_bootstrap(tmp_path, env):
    _run_app(tmp_path, env, """
try:
    import app
except RuntimeError:
    pass
else:
    raise AssertionError('Insecure app import unexpectedly succeeded')
""")
    assert not (tmp_path / "fixture.sqlite").exists()


@pytest.mark.parametrize("env,secure", [
    ({"FLASK_ENV": "production", "RAILWAY_SERVICE_ID": "fixture"}, True),
    ({"FLASK_ENV": None, "RAILWAY_SERVICE_ID": "fixture"}, True),
    ({"FLASK_ENV": " PRODUCTION "}, True),
    ({"FLASK_ENV": "development", "SECRET_KEY": None}, False),
    ({"FLASK_ENV": "testing"}, False),
])
def test_full_app_login_signatures_and_configuration(tmp_path, env, secure):
    _run_app(tmp_path, env, """
from datetime import datetime
from http.cookies import SimpleCookie
from flask import Flask
from flask_login.utils import encode_cookie
from itsdangerous import URLSafeTimedSerializer
from app import (app, db, limiter, _confirm_verification_token, _verify_delete_token,
                 _VERIFY_TOKEN_SALT, _DELETE_ACCOUNT_SALT)
from models import User
assert not app.debug and not app.testing
assert app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///')
limiter.enabled = False
with app.app_context():
    # G04: import must NEVER create the fixture's tables. Test fixtures
    # explicitly initialize their ephemeral SQLite database themselves.
    db.create_all()
    user = User(email='u02@example.invalid', full_name='Fictitious U02',
                email_verified_at=datetime.utcnow())
    user.set_password('FictitiousPassword123!')
    db.session.add(user)
    db.session.commit()
    uid = user.id
client = app.test_client()
response = client.post('/api/login', base_url='https://fixture.example.invalid',
    json={'email': 'u02@example.invalid', 'password': 'FictitiousPassword123!', 'remember': True})
assert response.status_code == 200
cookies = SimpleCookie()
for header in response.headers.getlist('Set-Cookie'):
    cookies.load(header)
assert {'session', 'remember_token'} <= set(cookies)
for name in ('session', 'remember_token'):
    assert bool(cookies[name]['secure']) == EXPECT_SECURE
    assert cookies[name]['httponly']
    assert cookies[name]['samesite'] == 'Lax'
assert client.get('/dashboard', base_url='https://fixture.example.invalid').status_code == 200
client.delete_cookie('session', domain='fixture.example.invalid')
assert client.get('/dashboard', base_url='https://fixture.example.invalid').status_code == 200
# Reconstruct prior production signature policy with the SAME fixture key.
old = Flask('u02-previous-policy')
old.config['SECRET_KEY'] = app.config['SECRET_KEY']
with app.app_context():
    identity = db.session.get(User, uid).get_id()
old_session = old.session_interface.get_signing_serializer(old).dumps({'_user_id': identity, '_fresh': True})
client = app.test_client()
client.set_cookie('session', old_session, domain='fixture.example.invalid')
assert client.get('/dashboard', base_url='https://fixture.example.invalid').status_code == 200
with old.app_context():
    old_remember = encode_cookie(identity)
client.delete_cookie('session', domain='fixture.example.invalid')
client.set_cookie('remember_token', old_remember, domain='fixture.example.invalid')
assert client.get('/dashboard', base_url='https://fixture.example.invalid').status_code == 200
s = URLSafeTimedSerializer(old.config['SECRET_KEY'])
token = s.dumps('u02@example.invalid', salt=_VERIFY_TOKEN_SALT)
assert _confirm_verification_token(token) == ('u02@example.invalid', None)
token = s.dumps(uid, salt=_DELETE_ACCOUNT_SALT)
assert _verify_delete_token(token, uid) == (True, '')
assert _verify_delete_token(token, uid + 1)[0] is False
assert client.get('/healthz', base_url='https://fixture.example.invalid').status_code == 200
""".replace("EXPECT_SECURE", repr(secure)))
