"""
Tests del callback de Google OAuth (/auth/google/callback).

Bug corregido (2026-06-11): un usuario NUEVO que entraba con Google era
redirigido a /login/?error=account_disabled. Causa: el `default=True` de la
columna users.is_active solo se aplica en el INSERT (flush), por lo que el
objeto User recién construido tenía is_active=None y el chequeo
`if not user.is_active` —que corre antes del commit— lo trataba como
deshabilitado. Además la cuenta nunca llegaba a crearse (no había commit).

Casos cubiertos:
  1. Usuario nuevo con Google → login OK, redirige a /dashboard, cuenta
     creada con is_active=True y email verificado.
  2. Usuario existente con email/password → login OK, se vincula google_id
     y se marca el email como verificado.
  3. Usuario existente realmente deshabilitado (is_active=False en BD) →
     redirige a /login/?error=account_disabled y NO inicia sesión.
  4. Google no devuelve email → redirige a /login/?error=no_email.

Diseño: se fuerza _google_oauth_enabled=True y se sustituye google_oauth por
un mock a nivel de módulo (no hay red en tests y no depende de que las env
vars GOOGLE_* existieran cuando otro módulo de tests importó app primero).
"""

import sys
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-google-oauth")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app as app_module
from app import app as flask_app, db
from models import User


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _app():
    flask_app.config["TESTING"]               = True
    flask_app.config["RATELIMIT_ENABLED"]     = False
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    flask_app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {}
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope="module", autouse=True)
def _google_oauth_mock(_app):
    """Activa el flag OAuth y garantiza que app.google_oauth existe como mock.

    Si app se importó sin GOOGLE_CLIENT_ID/SECRET (caso habitual en CI),
    oauth.register nunca se ejecutó y el atributo google_oauth no existe.
    """
    created = not hasattr(app_module, "google_oauth")
    if created:
        app_module.google_oauth = MagicMock()
    with patch.object(app_module, "_google_oauth_enabled", True):
        yield
    if created:
        del app_module.google_oauth


@pytest.fixture
def client(_app):
    return _app.test_client()


@pytest.fixture(autouse=True)
def _clean_users(_app):
    yield
    db.session.rollback()
    User.query.delete()
    db.session.commit()


def _mock_google_token(email, sub="google-sub-1", given_name="Ana", family_name="García"):
    return {
        "userinfo": {
            "email":       email,
            "sub":         sub,
            "given_name":  given_name,
            "family_name": family_name,
        }
    }


def _callback(client, token):
    with patch.object(app_module.google_oauth, "authorize_access_token", return_value=token):
        return client.get("/auth/google/callback")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_usuario_nuevo_google_inicia_sesion(client):
    """Regresión del bug: usuario nuevo NO debe recibir account_disabled."""
    resp = _callback(client, _mock_google_token("nueva@example.com"))

    assert resp.status_code == 302
    assert "account_disabled" not in resp.headers["Location"]
    assert resp.headers["Location"].endswith("/dashboard")

    user = User.query.filter_by(email="nueva@example.com").first()
    assert user is not None, "La cuenta debe crearse en el callback"
    assert user.is_active is True
    assert user.email_verified_at is not None
    assert user.google_id == "google-sub-1"
    assert user.full_name == "Ana García"


def test_usuario_existente_password_vincula_google(client):
    user = User(email="clasica@example.com", full_name="Clásica López")
    user.set_password("password-segura-123")
    db.session.add(user)
    db.session.commit()

    resp = _callback(client, _mock_google_token("clasica@example.com", sub="sub-clasica"))

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")

    user = User.query.filter_by(email="clasica@example.com").first()
    assert user.google_id == "sub-clasica"
    assert user.email_verified_at is not None, "Google verifica el email"
    assert user.password_hash is not None, "No debe perder su contraseña"


def test_usuario_deshabilitado_real_no_entra(client):
    user = User(email="baja@example.com", is_active=False)
    db.session.add(user)
    db.session.commit()

    resp = _callback(client, _mock_google_token("baja@example.com", sub="sub-baja"))

    assert resp.status_code == 302
    assert "error=account_disabled" in resp.headers["Location"]
    # No debe quedar sesión iniciada
    me = client.get("/api/me")
    assert me.get_json()["user"] is None


def test_google_sin_email_redirige_no_email(client):
    resp = _callback(client, {"userinfo": {"sub": "sin-email"}})

    assert resp.status_code == 302
    assert "error=no_email" in resp.headers["Location"]
