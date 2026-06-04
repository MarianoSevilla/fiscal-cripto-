"""
Tests para el endpoint /api/me — campo is_fiscal_advisor y visibilidad del menú nav.

Casos cubiertos:
  1. Usuario normal: is_admin=False, is_fiscal_advisor=False.
  2. fiscal_advisor: is_admin=False, is_fiscal_advisor=True.
  3. admin: is_admin=True, is_fiscal_advisor depende de rol.
  4. No autenticado: user=None.
  5. /admin/asesoramiento devuelve 200 para fiscal_advisor (protección intacta).
  6. /admin/asesoramiento devuelve 404 para usuario normal.
"""

import sys
import os
import tempfile
from datetime import datetime

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-nav-advisor")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app    import app as flask_app, db
from models import User


@pytest.fixture(scope="module")
def _app():
    flask_app.config["TESTING"]               = True
    flask_app.config["RATELIMIT_ENABLED"]     = False
    flask_app.config["WTF_CSRF_ENABLED"]      = False
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    flask_app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {}
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


def _make_user(_app, email, role):
    with _app.app_context():
        u = User(email=email, full_name=f"Test {role}", role=role,
                 email_verified_at=datetime.utcnow())
        u.set_password("pass-nav-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
        db.session.remove()
    return uid


@pytest.fixture(scope="module")
def normal_id(_app):    return _make_user(_app, "nav_normal@example.com",  "user")
@pytest.fixture(scope="module")
def advisor_id(_app):   return _make_user(_app, "nav_advisor@example.com", "fiscal_advisor")
@pytest.fixture(scope="module")
def admin_id(_app):     return _make_user(_app, "nav_admin@example.com",   "admin")

@pytest.fixture
def client(_app):       return _app.test_client()

@pytest.fixture(autouse=True)
def _clean_login(_app):
    yield
    from flask import g
    g.pop("_login_user", None)


def _login(client, email):
    r = client.post("/api/login", json={"email": email, "password": "pass-nav-1234"},
                    content_type="application/json")
    assert r.status_code == 200, f"Login falló: {r.get_json()}"


# ── Tests /api/me ─────────────────────────────────────────────────────────────

def test_normal_no_es_admin_ni_advisor(client, normal_id):
    _login(client, "nav_normal@example.com")
    r = client.get("/api/me")
    assert r.status_code == 200
    u = r.get_json()["user"]
    assert u["is_admin"]          is False
    assert u["is_fiscal_advisor"] is False


def test_advisor_is_fiscal_advisor(client, advisor_id):
    _login(client, "nav_advisor@example.com")
    r = client.get("/api/me")
    assert r.status_code == 200
    u = r.get_json()["user"]
    assert u["is_fiscal_advisor"] is True
    assert u["is_admin"]          is False


def test_admin_is_admin(client, admin_id):
    _login(client, "nav_admin@example.com")
    r = client.get("/api/me")
    assert r.status_code == 200
    u = r.get_json()["user"]
    assert u["is_admin"] is True


def test_anonimo_user_none(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.get_json()["user"] is None


# ── Tests protección /admin/asesoramiento ─────────────────────────────────────

def test_advisor_puede_acceder_panel(client, advisor_id):
    _login(client, "nav_advisor@example.com")
    r = client.get("/admin/asesoramiento")
    assert r.status_code == 200


def test_normal_no_puede_acceder_panel(client, normal_id):
    _login(client, "nav_normal@example.com")
    r = client.get("/admin/asesoramiento")
    assert r.status_code in (302, 403, 404)  # redirige al login o deniega
