"""
Tests para solicitudes de asesoramiento anónimas (user_id=NULL)

Casos cubiertos:
  1. Usuario autenticado crea solicitud → user_id guardado, estado submitted.
  2a. BD acepta user_id=NULL (nullable constraint) — test directo, sin endpoint.
  2b. Endpoint devuelve 200 para una solicitud anónima (sin sesión).
  3. Admin ve solicitudes anónimas y autenticadas.
  4. Usuario autenticado solo ve sus propias solicitudes (no las anónimas).
  5. to_dict() no falla con user_id=NULL (basic y full).
  6. Funciones de email no fallan con user_id=NULL.

Nota de aislamiento
-------------------
Cada test que verifica estado en BD lo hace directamente vía ORM (sin pasar
por el endpoint) para evitar interferencias del identity map de SQLAlchemy entre
tests que comparten la misma session SQLite. Los tests de endpoint solo validan
la respuesta HTTP; los de BD validan los datos persistidos.
"""

import sys
import os
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest

# ── Entorno antes de importar app ─────────────────────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-anon-advisory")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app    import app as flask_app, db
from models import User, FiscalAdvisoryRequest


# ── Payload mínimo válido ──────────────────────────────────────────────────────

_VALID_PAYLOAD = {
    "full_name":             "Test Solicitante",
    "email":                 "solicitante_test@example.com",
    "phone":                 "+34 600 000 000",
    "case_description":      "Necesito ayuda con mi declaración de criptomonedas del año pasado.",
    "tax_residence_country": "España",
    "tax_year":              2024,
    "service_type":          "presupuesto_personalizado",
    "operation_types":       [],
    "current_situation":     [],
}


# ── Fixtures ───────────────────────────────────────────────────────────────────

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
def admin_user(_app):
    """Usuario con role=fiscal_advisor."""
    with _app.app_context():
        u = User(
            email="admin_anon_adv@example.com",
            full_name="Admin Anon Test",
            role="fiscal_advisor",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("admin-pass-anon-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
        db.session.remove()
    yield uid
    with _app.app_context():
        FiscalAdvisoryRequest.query.filter_by(user_id=uid).delete()
        db.session.commit()
        User.query.filter_by(id=uid).delete()
        db.session.commit()
        db.session.remove()


@pytest.fixture(scope="module")
def normal_user(_app):
    """Usuario sin privilegios."""
    with _app.app_context():
        u = User(
            email="normal_anon_adv@example.com",
            full_name="Normal Anon Test",
            role="user",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("normal-pass-anon-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
        db.session.remove()
    yield uid
    with _app.app_context():
        FiscalAdvisoryRequest.query.filter_by(user_id=uid).delete()
        db.session.commit()
        User.query.filter_by(id=uid).delete()
        db.session.commit()
        db.session.remove()


@pytest.fixture
def client(_app):
    """Cliente Flask fresco por test (sin cookies compartidas entre tests)."""
    return _app.test_client()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _login_admin(client):
    r = client.post("/api/login", json={
        "email":    "admin_anon_adv@example.com",
        "password": "admin-pass-anon-1234",
    })
    assert r.status_code == 200, f"Login admin falló: {r.get_json()}"


def _login_normal(client):
    r = client.post("/api/login", json={
        "email":    "normal_anon_adv@example.com",
        "password": "normal-pass-anon-1234",
    })
    assert r.status_code == 200, f"Login normal falló: {r.get_json()}"


def _post_solicitud(client, payload=None):
    """Envía POST /api/asesoramiento/solicitar con emails mockeados."""
    data = payload or _VALID_PAYLOAD
    with patch("app._send_advisory_confirmation_email"), \
         patch("app._send_advisory_internal_notification"):
        return client.post(
            "/api/asesoramiento/solicitar",
            json=data,
            content_type="application/json",
        )


def _make_advisory_direct(_app, user_id=None, status="submitted"):
    """Crea un advisory directamente en BD (sin endpoint) y devuelve su id.
    Más robusto para tests de BD: evita interferencias del identity map.
    """
    with _app.app_context():
        adv = FiscalAdvisoryRequest(
            user_id               = user_id,
            full_name             = "Test Directo",
            email                 = "directo@example.com",
            tax_residence_country = "España",
            tax_year              = 2024,
            service_type          = "presupuesto_personalizado",
            case_description      = "Descripción de prueba creada directamente en BD.",
            status                = status,
        )
        db.session.add(adv)
        db.session.commit()
        adv_id = adv.id
        db.session.remove()
    return adv_id


def _delete_advisory(_app, adv_id):
    """Borra un advisory por id con session limpia."""
    with _app.app_context():
        FiscalAdvisoryRequest.query.filter_by(id=adv_id).delete()
        db.session.commit()
        db.session.remove()


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_usuario_autenticado_crea_solicitud(client, normal_user, _app):
    """Usuario autenticado crea solicitud → user_id correcto, estado submitted."""
    _login_normal(client)
    r = _post_solicitud(client)
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data.get("ok") is True

    adv_id = data["advisory_id"]
    # Verificar en BD con session limpia (sin reutilizar la del request)
    with _app.app_context():
        db.session.remove()  # Forzar session completamente nueva
        adv = FiscalAdvisoryRequest.query.filter_by(id=adv_id).first()
        assert adv is not None
        assert adv.user_id == normal_user, \
            f"Se esperaba user_id={normal_user}, se obtuvo {adv.user_id}"
        assert adv.status == "submitted"
        db.session.delete(adv)
        db.session.commit()
        db.session.remove()


def test_bd_acepta_user_id_null(_app):
    """La BD acepta user_id=NULL: INSERT directo sin IntegrityError."""
    with _app.app_context():
        db.session.remove()
        adv = FiscalAdvisoryRequest(
            user_id               = None,
            full_name             = "Visitante Anónimo",
            email                 = "anonimo_bd@example.com",
            tax_residence_country = "España",
            tax_year              = 2024,
            service_type          = "presupuesto_personalizado",
            case_description      = "Descripción de prueba para test de constraint nullable.",
            status                = "submitted",
        )
        db.session.add(adv)
        db.session.commit()   # No debe lanzar IntegrityError
        assert adv.id is not None
        assert adv.user_id is None
        db.session.delete(adv)
        db.session.commit()
        db.session.remove()


def test_endpoint_acepta_solicitud_anonima(client, _app):
    """Endpoint /api/asesoramiento/solicitar devuelve 200 sin sesión activa."""
    # client es función-scoped: nuevo objeto sin cookies de tests anteriores
    r = _post_solicitud(client)
    data = r.get_json()
    assert r.status_code == 200, data
    assert data.get("ok") is True
    assert "advisory_id" in data
    # Cleanup
    _delete_advisory(_app, data["advisory_id"])


def test_admin_ve_solicitudes_autenticada_y_anonima(client, normal_user, admin_user, _app):
    """Admin puede ver solicitudes tanto de usuarios registrados como anónimas."""
    # Crear una autenticada directamente en BD
    auth_id = _make_advisory_direct(_app, user_id=normal_user)
    # Crear una anónima directamente en BD
    anon_id = _make_advisory_direct(_app, user_id=None)

    # Admin las ve ambas en la lista
    _login_admin(client)
    r_lista = client.get("/api/admin/asesoramiento/solicitudes")
    assert r_lista.status_code == 200
    ids = [item["id"] for item in r_lista.get_json()]
    assert auth_id in ids, f"Solicitud autenticada {auth_id} no está en la lista admin"
    assert anon_id in ids, f"Solicitud anónima {anon_id} no está en la lista admin"

    # Limpieza
    _delete_advisory(_app, auth_id)
    _delete_advisory(_app, anon_id)


def test_usuario_autenticado_solo_ve_las_suyas(client, normal_user, _app):
    """Usuario autenticado no ve solicitudes anónimas en /api/asesoramiento/mis-solicitudes."""
    anon_id = _make_advisory_direct(_app, user_id=None)

    _login_normal(client)
    r = client.get("/api/asesoramiento/mis-solicitudes")
    assert r.status_code == 200
    ids = [item["id"] for item in r.get_json()]
    assert anon_id not in ids, \
        f"La solicitud anónima {anon_id} no debe aparecer en las solicitudes del usuario"

    _delete_advisory(_app, anon_id)


def test_to_dict_no_falla_con_user_id_null(_app):
    """to_dict() (basic y full) funciona sin lanzar excepciones con user_id=None."""
    anon_id = _make_advisory_direct(_app, user_id=None)

    with _app.app_context():
        db.session.remove()
        adv = FiscalAdvisoryRequest.query.filter_by(id=anon_id).first()
        assert adv is not None
        assert adv.user_id is None

        d_basic = adv.to_dict()
        assert d_basic["user_id"] is None
        assert d_basic["id"] == anon_id
        assert d_basic["status"] == "submitted"

        d_full = adv.to_dict(full=True)
        assert d_full["user_id"] is None
        assert "case_description" in d_full
        db.session.remove()

    _delete_advisory(_app, anon_id)


def test_emails_no_fallan_con_user_id_null(_app):
    """Las funciones de email no leen user_id y no lanzan excepción con user_id=None."""
    from email_templates import (
        advisory_confirmation_email,
        advisory_status_email,
        advisory_quote_email,
    )

    with _app.app_context():
        db.session.remove()
        adv = FiscalAdvisoryRequest(
            user_id               = None,
            full_name             = "Anónimo Email",
            email                 = "anon_email@example.com",
            tax_residence_country = "España",
            tax_year              = 2024,
            service_type          = "presupuesto_personalizado",
            case_description      = "Descripción de prueba para test de emails con user_id nulo.",
            status                = "submitted",
            quoted_amount         = 9900,
            quote_message         = "Presupuesto de prueba.",
        )
        db.session.add(adv)
        db.session.commit()
        adv_id = adv.id

        try:
            html, text = advisory_confirmation_email(adv)
            assert html and len(html) > 50
            assert text and len(text) > 10

            # submitted no genera email → (None, None) es resultado válido
            html2, text2 = advisory_status_email(adv, note="Nota de prueba")
            assert html2 is None or len(html2) > 50

            html3, text3 = advisory_quote_email(adv, payment_url="https://example.com/pay/token")
            assert html3 and len(html3) > 50
            assert text3 and len(text3) > 10

        finally:
            db.session.delete(adv)
            db.session.commit()
            db.session.remove()
