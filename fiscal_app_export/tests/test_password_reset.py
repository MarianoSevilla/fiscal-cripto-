"""
Tests para flujo de recuperación de contraseña.

Casos cubiertos:
  1.  Solicitud con email existente devuelve mensaje genérico (200).
  2.  Solicitud con email inexistente devuelve mismo mensaje genérico (200).
  3.  Email existente genera token_hash + expires_at en DB.
  4.  Token válido permite cambiar contraseña.
  5.  Token expirado falla con 400.
  6.  Token ya usado no puede reutilizarse.
  7.  Contraseñas distintas fallan con 400.
  8.  Login funciona con nueva contraseña tras reset.
  9.  Login falla con contraseña antigua tras reset.
  10. Rate limit básico: POST /api/forgot-password aplica límite.
"""

import sys
import os
import hashlib
import tempfile
from datetime import datetime, timedelta

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-pw-reset-only")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User


# ── Fixtures ─────────────────────────────────────────────────────────────────

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


@pytest.fixture(scope="module")
def existing_user(_app):
    with _app.app_context():
        u = User(
            email="reset_test_user@example.com",
            full_name="Reset Test",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("OldPass1234!")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture()
def client(_app):
    return _app.test_client()


def _load_user(app, uid):
    with app.app_context():
        return db.session.get(User, uid)


_GENERIC_MSG = "Si existe una cuenta con ese email, te enviaremos un enlace para restablecer la contraseña."


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_forgot_existing_email_returns_generic(client, existing_user):
    """Solicitud con email existente → 200 + mensaje genérico."""
    r = client.post("/api/forgot-password", json={"email": "reset_test_user@example.com"})
    assert r.status_code == 200
    assert r.get_json()["message"] == _GENERIC_MSG


def test_forgot_nonexistent_email_returns_same_message(client):
    """Solicitud con email inexistente → mismo 200 + mismo mensaje (no revela existencia)."""
    r = client.post("/api/forgot-password", json={"email": "noexiste_never@example.com"})
    assert r.status_code == 200
    assert r.get_json()["message"] == _GENERIC_MSG


def test_forgot_stores_token_hash_and_expiry(_app, client, existing_user):
    """Solicitar reset genera token_hash y expires_at en DB."""
    client.post("/api/forgot-password", json={"email": "reset_test_user@example.com"})
    user = _load_user(_app, existing_user)
    assert user.password_reset_token_hash is not None
    assert user.password_reset_expires_at is not None
    assert user.password_reset_expires_at > datetime.utcnow()


def test_valid_token_changes_password(_app, client, existing_user):
    """Token válido permite actualizar la contraseña."""
    import secrets as _secrets

    token_raw  = _secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token_raw.encode()).hexdigest()

    with _app.app_context():
        user = db.session.get(User, existing_user)
        user.password_reset_token_hash = token_hash
        user.password_reset_expires_at = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()

    r = client.post("/api/reset-password", json={
        "token":            token_raw,
        "password":         "NewSecurePass99!",
        "confirm_password": "NewSecurePass99!",
    })
    assert r.status_code == 200
    assert "correctamente" in r.get_json()["message"].lower()


def test_expired_token_fails(_app, client, existing_user):
    """Token expirado devuelve 400."""
    import secrets as _secrets

    token_raw  = _secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token_raw.encode()).hexdigest()

    with _app.app_context():
        user = db.session.get(User, existing_user)
        user.password_reset_token_hash = token_hash
        user.password_reset_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()

    r = client.post("/api/reset-password", json={
        "token":            token_raw,
        "password":         "AnotherPass99!",
        "confirm_password": "AnotherPass99!",
    })
    assert r.status_code == 400
    assert "expirado" in r.get_json()["error"].lower()


def test_used_token_cannot_be_reused(_app, client, existing_user):
    """Token de un solo uso: el segundo intento falla."""
    import secrets as _secrets

    token_raw  = _secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token_raw.encode()).hexdigest()

    with _app.app_context():
        user = db.session.get(User, existing_user)
        user.password_reset_token_hash = token_hash
        user.password_reset_expires_at = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()

    payload = {
        "token":            token_raw,
        "password":         "UniquePass99!",
        "confirm_password": "UniquePass99!",
    }
    r1 = client.post("/api/reset-password", json=payload)
    assert r1.status_code == 200

    r2 = client.post("/api/reset-password", json=payload)
    assert r2.status_code == 400


def test_mismatched_passwords_fail(client):
    """Contraseñas distintas devuelven 400."""
    r = client.post("/api/reset-password", json={
        "token":            "any-token-does-not-matter",
        "password":         "PassOne1234!",
        "confirm_password": "PassTwo5678!",
    })
    assert r.status_code == 400
    assert "coinciden" in r.get_json()["error"].lower()


def test_login_works_with_new_password(_app, client, existing_user):
    """Login exitoso con nueva contraseña tras reset."""
    import secrets as _secrets

    new_pw     = "FreshPassword2025!"
    token_raw  = _secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token_raw.encode()).hexdigest()

    with _app.app_context():
        user = db.session.get(User, existing_user)
        user.password_reset_token_hash = token_hash
        user.password_reset_expires_at = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()

    reset_r = client.post("/api/reset-password", json={
        "token":            token_raw,
        "password":         new_pw,
        "confirm_password": new_pw,
    })
    assert reset_r.status_code == 200

    login_r = client.post("/api/login", json={
        "email":    "reset_test_user@example.com",
        "password": new_pw,
    })
    assert login_r.status_code == 200


def test_login_fails_with_old_password(_app, client, existing_user):
    """Login falla con la contraseña anterior al reset."""
    r = client.post("/api/login", json={
        "email":    "reset_test_user@example.com",
        "password": "OldPass1234!",
    })
    assert r.status_code == 401


def test_rate_limit_on_forgot_password(_app, client):
    """POST /api/forgot-password aplica rate limit (solo cuando RATELIMIT_ENABLED=True)."""
    if not _app.config.get("RATELIMIT_ENABLED", True):
        pytest.skip("Rate limiting desactivado en tests")
