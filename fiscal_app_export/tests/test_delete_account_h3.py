"""
Tests H3 — Delete account con reautenticación (itsdangerous, sin BD).

Casos cubiertos:
  1.  Sin sesión → 401.
  2.  Usuario con contraseña correcta → cuenta anonimizada.
  3.  Usuario con contraseña incorrecta → 403, cuenta intacta.
  4.  Usuario con contraseña ausente en body → 400, cuenta intacta.
  5.  Usuario OAuth solicita token → 200, email enviado.
  6.  Usuario OAuth confirma token válido → cuenta anonimizada.
  7.  Usuario OAuth intenta token con string inválido → 403.
  8.  Usuario OAuth intenta token expirado → 403, mensaje "expirado".
  9.  Token generado para otro usuario → 403.
  10. Usuario con contraseña no puede usar /request → 400.

Diseño del token (Opción B aprobada)
--------------------------------------
El token es un URLSafeTimedSerializer firmado que codifica el user_id.
No se persiste en BD: la firma y el TTL son auto-contenidos en el token.
La validación comprueba firma, TTL y que el user_id del token coincida
con current_user.id (protección cruzada de usuarios).

Nota de aislamiento
--------------------
El fixture autouse _reset_session limpia Flask-Login (g._login_user) y el
identity map de SQLAlchemy entre tests para evitar datos stale entre requests
que comparten el mismo app context de módulo.
"""

import sys
import os
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest
from itsdangerous import URLSafeTimedSerializer

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-h3-delete")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app    import app as flask_app, db, _DELETE_ACCOUNT_SALT
from models import User


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


@pytest.fixture
def client(_app):
    """Cliente Flask fresco por test (sin cookies compartidas)."""
    return _app.test_client()


@pytest.fixture(autouse=True)
def _reset_session(_app):
    """Limpia Flask-Login y el identity map de SQLAlchemy entre tests.

    Evita que db.session.get() devuelva objetos stale de requests anteriores,
    lo que provocaría que check_password() falle o que current_user tenga
    datos de un usuario distinto.
    """
    yield
    from flask import g
    g.pop("_login_user", None)
    db.session.remove()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_pw_user(_app, email, password):
    with _app.app_context():
        db.session.remove()
        u = User(
            email=email, full_name="Test PW User", role="user",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        uid = u.id
        db.session.remove()
    return uid


def _make_oauth_user(_app, email):
    with _app.app_context():
        db.session.remove()
        u = User(
            email=email, full_name="Test OAuth User", role="user",
            google_id=f"google-{email}", email_verified_at=datetime.utcnow(),
        )
        db.session.add(u)
        db.session.commit()
        uid = u.id
        db.session.remove()
    return uid


def _login(client, email, password):
    r = client.post("/api/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login falló: {r.get_json()}"


def _inject_oauth_session(client, uid):
    """Inyecta sesión Flask-Login para usuario OAuth (sin pasar por /api/login)."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"]   = True


def _make_delete_token(_app, user_id: int, expired: bool = False) -> str:
    """Genera un token itsdangerous para el user_id dado.

    Si expired=True, parchea _DELETE_TOKEN_TTL a 0 en la verificación posterior.
    El token en sí siempre se genera correctamente; la expiración se simula
    parcheando el TTL al llamar al endpoint, no al crear el token.
    Devuelve el token raw para usar directamente en el POST.
    """
    with _app.app_context():
        s = URLSafeTimedSerializer(_app.config["SECRET_KEY"])
        return s.dumps(user_id, salt=_DELETE_ACCOUNT_SALT)


def _user_is_active(_app, uid):
    with _app.app_context():
        db.session.remove()
        u = db.session.get(User, uid)
        result = u.is_active if u else False
        db.session.remove()
    return result


def _cleanup(_app, uid):
    with _app.app_context():
        db.session.remove()
        u = db.session.get(User, uid)
        if u:
            db.session.delete(u)
            db.session.commit()
        db.session.remove()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_sin_sesion_devuelve_401(client, _app):
    """Caso 1: sin sesión activa → 401."""
    r = client.post("/api/delete-account", json={})
    assert r.status_code == 401


def test_pw_user_contrasena_correcta(client, _app):
    """Caso 2: contraseña correcta → 200, cuenta anonimizada."""
    uid = _make_pw_user(_app, "h3_pw_ok@test.com", "Correct-Pass-123!")
    _login(client, "h3_pw_ok@test.com", "Correct-Pass-123!")

    r = client.post("/api/delete-account",
                    json={"password": "Correct-Pass-123!"},
                    content_type="application/json")
    assert r.status_code == 200, r.get_json()
    assert r.get_json().get("message") == "Cuenta eliminada correctamente."
    assert not _user_is_active(_app, uid)
    _cleanup(_app, uid)


def test_pw_user_contrasena_incorrecta(client, _app):
    """Caso 3: contraseña incorrecta → 403, cuenta intacta."""
    uid = _make_pw_user(_app, "h3_pw_wrong@test.com", "Right-Pass-123!")
    _login(client, "h3_pw_wrong@test.com", "Right-Pass-123!")

    r = client.post("/api/delete-account",
                    json={"password": "WRONG-password"},
                    content_type="application/json")
    assert r.status_code == 403
    assert _user_is_active(_app, uid)
    _cleanup(_app, uid)


def test_pw_user_contrasena_ausente(client, _app):
    """Caso 4: campo password ausente → 400, cuenta intacta."""
    uid = _make_pw_user(_app, "h3_pw_missing@test.com", "Some-Pass-123!")
    _login(client, "h3_pw_missing@test.com", "Some-Pass-123!")

    r = client.post("/api/delete-account", json={}, content_type="application/json")
    assert r.status_code == 400
    assert _user_is_active(_app, uid)
    _cleanup(_app, uid)


def test_oauth_solicita_token_envia_email(client, _app):
    """Caso 5: /request para OAuth → 200, email enviado (sin escritura en BD)."""
    uid = _make_oauth_user(_app, "h3_oauth_req@test.com")
    _inject_oauth_session(client, uid)

    # Parcheamos resend.api_key para que no aborte antes de Emails.send,
    # y Emails.send para no enviar email real.
    import resend as _resend
    with patch.object(_resend, "api_key", "test-key"), \
         patch("resend.Emails.send", return_value={"id": "mock-id"}) as mock_send:
        r = client.post("/api/delete-account/request", content_type="application/json")

    assert r.status_code == 200, r.get_json()
    assert r.get_json().get("ok") is True
    mock_send.assert_called_once()

    # Verificar que NO se escribió nada en BD (no existen esas columnas)
    with _app.app_context():
        db.session.remove()
        u = db.session.get(User, uid)
        assert not hasattr(u, "delete_token_hash"), \
            "delete_token_hash no debería existir en el modelo"
        db.session.remove()

    _cleanup(_app, uid)


def test_oauth_token_valido_elimina_cuenta(client, _app):
    """Caso 6: token itsdangerous válido → 200, cuenta anonimizada."""
    uid   = _make_oauth_user(_app, "h3_oauth_ok@test.com")
    token = _make_delete_token(_app, uid)
    _inject_oauth_session(client, uid)

    r = client.post("/api/delete-account",
                    json={"token": token},
                    content_type="application/json")
    assert r.status_code == 200, r.get_json()
    assert r.get_json().get("message") == "Cuenta eliminada correctamente."
    assert not _user_is_active(_app, uid)
    _cleanup(_app, uid)


def test_oauth_token_invalido(client, _app):
    """Caso 7: string inválido como token → 403."""
    uid = _make_oauth_user(_app, "h3_oauth_bad@test.com")
    _inject_oauth_session(client, uid)

    r = client.post("/api/delete-account",
                    json={"token": "esto-no-es-un-token-valido"},
                    content_type="application/json")
    assert r.status_code == 403
    assert r.get_json().get("error") == "Código de confirmación inválido."
    assert _user_is_active(_app, uid)
    _cleanup(_app, uid)


def test_oauth_token_expirado(client, _app):
    """Caso 8: token expirado (TTL parcheado a 0) → 403, mensaje 'expirado'."""
    uid   = _make_oauth_user(_app, "h3_oauth_exp@test.com")
    token = _make_delete_token(_app, uid)
    _inject_oauth_session(client, uid)

    # Parchear _DELETE_TOKEN_TTL a -1: itsdangerous comprueba age > max_age,
    # con max_age=-1 cualquier token está expirado al instante.
    with patch("app._DELETE_TOKEN_TTL", -1):
        r = client.post("/api/delete-account",
                        json={"token": token},
                        content_type="application/json")

    assert r.status_code == 403
    assert "expirado" in r.get_json().get("error", "").lower()
    assert _user_is_active(_app, uid)
    _cleanup(_app, uid)


def test_oauth_token_de_otro_usuario(client, _app):
    """Caso 9: token generado para usuario A usado con sesión de usuario B → 403."""
    uid_a = _make_oauth_user(_app, "h3_oauth_usera@test.com")
    uid_b = _make_oauth_user(_app, "h3_oauth_userb@test.com")

    # Token firmado para usuario A
    token_a = _make_delete_token(_app, uid_a)

    # Sesión de usuario B
    _inject_oauth_session(client, uid_b)

    r = client.post("/api/delete-account",
                    json={"token": token_a},
                    content_type="application/json")
    assert r.status_code == 403
    assert r.get_json().get("error") == "Código de confirmación inválido."
    assert _user_is_active(_app, uid_b), "Usuario B no debe ser afectado"
    assert _user_is_active(_app, uid_a), "Usuario A no debe ser afectado"
    _cleanup(_app, uid_a)
    _cleanup(_app, uid_b)


def test_pw_user_no_puede_usar_request_endpoint(client, _app):
    """Caso 10: /request solo aplica a OAuth; usuario con contraseña recibe 400."""
    uid = _make_pw_user(_app, "h3_pw_request@test.com", "Pass-For-Request-1!")
    _login(client, "h3_pw_request@test.com", "Pass-For-Request-1!")

    r = client.post("/api/delete-account/request", content_type="application/json")
    assert r.status_code == 400
    _cleanup(_app, uid)
