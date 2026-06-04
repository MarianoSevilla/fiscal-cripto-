"""
Tests para el endpoint POST /api/admin/asesoramiento/solicitudes/<id>/mensaje

Casos cubiertos:
  1. Advisor puede enviar mensaje sin importe.
  2. Admin puede enviar mensaje sin importe.
  3. Usuario normal recibe 403.
  4. Anónimo recibe 401/403.
  5. Email se envía (mock).
  6. No se crea presupuesto (quoted_amount = None).
  7. No se genera payment_link_token.
  8. Estado cambia a pendiente_info cuando set_pendiente_info=True.
  9. Estado se mantiene cuando set_pendiente_info=False.
  10. Mensaje vacío devuelve 400.
  11. Flujo de presupuesto existente no se rompe (enviar-presupuesto sigue requiriendo importe).
  12. Nota interna registrada en advisory_internal_notes.
  13. Historial de estado registrado.
  14. No se puede enviar mensaje en estado paid_received (409).
"""

import sys
import os
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-mensaje-advisory")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app    import app as flask_app, db
from models import User, FiscalAdvisoryRequest, AdvisoryInternalNote, FiscalAdvisoryStatusHistory


# ── Payload mínimo ────────────────────────────────────────────────────────────

_VALID_ADVISORY = {
    "full_name":             "Cliente Test Mensaje",
    "email":                 "cliente_msg@example.com",
    "phone":                 "+34 600 111 222",
    "case_description":      "Tengo permutas con pérdidas en varios exchanges.",
    "tax_residence_country": "España",
    "tax_year":              2024,
    "service_type":          "presupuesto_personalizado",
    "operation_types":       [],
    "current_situation":     [],
}


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


def _make_user(_app, email, role, suffix):
    with _app.app_context():
        u = User(
            email=email,
            full_name=f"Test {suffix}",
            role=role,
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("pass-1234-test")
        db.session.add(u)
        db.session.commit()
        uid = u.id
        db.session.remove()
    return uid


@pytest.fixture(scope="module")
def advisor_id(_app):
    return _make_user(_app, "advisor_msg@example.com", "fiscal_advisor", "Advisor")


@pytest.fixture(scope="module")
def admin_id(_app):
    return _make_user(_app, "admin_msg@example.com", "admin", "Admin")


@pytest.fixture(scope="module")
def normal_id(_app):
    return _make_user(_app, "normal_msg@example.com", "user", "Normal")


@pytest.fixture
def client(_app):
    return _app.test_client()


@pytest.fixture(autouse=True)
def _clean_login(_app):
    yield
    from flask import g
    g.pop("_login_user", None)


def _login(client, email, password="pass-1234-test"):
    r = client.post("/api/login", json={"email": email, "password": password}, content_type="application/json")
    assert r.status_code == 200, f"Login falló para {email}: {r.get_json()}"


def _create_advisory(_app, status="submitted"):
    with _app.app_context():
        adv = FiscalAdvisoryRequest(
            full_name=_VALID_ADVISORY["full_name"],
            email=_VALID_ADVISORY["email"],
            tax_residence_country=_VALID_ADVISORY["tax_residence_country"],
            tax_year=_VALID_ADVISORY["tax_year"],
            service_type=_VALID_ADVISORY["service_type"],
            case_description=_VALID_ADVISORY["case_description"],
            status=status,
        )
        db.session.add(adv)
        db.session.commit()
        aid = adv.id
        db.session.remove()
    return aid


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_advisor_puede_enviar_mensaje(client, _app, advisor_id):
    """Test 1: Advisor envía mensaje sin importe — 200 OK."""
    aid = _create_advisory(_app)
    _login(client, "advisor_msg@example.com")
    with patch("app._send_advisory_message_email", return_value=True):
        r = client.post(
            f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
            json={"mensaje": "Necesitamos los CSVs de Bit2Me.", "set_pendiente_info": True},
            content_type="application/json",
        )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["email_sent"] is True


def test_admin_puede_enviar_mensaje(client, _app, admin_id):
    """Test 2: Admin (role=admin) envía mensaje — 200 OK."""
    aid = _create_advisory(_app)
    _login(client, "admin_msg@example.com")
    with patch("app._send_advisory_message_email", return_value=True):
        r = client.post(
            f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
            json={"mensaje": "Mensaje del admin.", "set_pendiente_info": False},
            content_type="application/json",
        )
    assert r.status_code == 200


def test_usuario_normal_no_puede(client, _app, normal_id):
    """Test 3: Usuario normal recibe 403."""
    aid = _create_advisory(_app)
    _login(client, "normal_msg@example.com")
    r = client.post(
        f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
        json={"mensaje": "Intento no autorizado."},
        content_type="application/json",
    )
    assert r.status_code in (403, 404)


def test_anonimo_no_puede(client, _app):
    """Test 4: Anónimo recibe 401 o 403."""
    aid = _create_advisory(_app)
    r = client.post(
        f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
        json={"mensaje": "Sin sesión."},
        content_type="application/json",
    )
    assert r.status_code in (401, 403, 404)


def test_email_se_envia(client, _app, advisor_id):
    """Test 5: _send_advisory_message_email se llama con los argumentos correctos."""
    aid = _create_advisory(_app)
    _login(client, "advisor_msg@example.com")
    with patch("app._send_advisory_message_email", return_value=True) as mock_send:
        client.post(
            f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
            json={"mensaje": "Por favor envíanos los archivos.", "set_pendiente_info": False},
            content_type="application/json",
        )
    mock_send.assert_called_once()
    advisory_arg, mensaje_arg = mock_send.call_args[0]
    assert advisory_arg.id == aid
    assert "archivos" in mensaje_arg


def test_no_se_crea_presupuesto(client, _app, advisor_id):
    """Test 6: quoted_amount permanece None tras enviar mensaje."""
    aid = _create_advisory(_app)
    _login(client, "advisor_msg@example.com")
    with patch("app._send_advisory_message_email", return_value=True):
        client.post(
            f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
            json={"mensaje": "Revisando tu caso.", "set_pendiente_info": False},
            content_type="application/json",
        )
    with _app.app_context():
        adv = FiscalAdvisoryRequest.query.get(aid)
        assert adv.quoted_amount is None
        db.session.remove()


def test_no_se_genera_payment_token(client, _app, advisor_id):
    """Test 7: payment_link_token permanece None tras enviar mensaje."""
    aid = _create_advisory(_app)
    _login(client, "advisor_msg@example.com")
    with patch("app._send_advisory_message_email", return_value=True):
        client.post(
            f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
            json={"mensaje": "Revisando tu caso.", "set_pendiente_info": False},
            content_type="application/json",
        )
    with _app.app_context():
        adv = FiscalAdvisoryRequest.query.get(aid)
        assert adv.payment_link_token is None
        db.session.remove()


def test_estado_cambia_a_pendiente_info(client, _app, advisor_id):
    """Test 8: set_pendiente_info=True cambia estado a pendiente_info."""
    aid = _create_advisory(_app, status="submitted")
    _login(client, "advisor_msg@example.com")
    with patch("app._send_advisory_message_email", return_value=True):
        r = client.post(
            f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
            json={"mensaje": "Necesitamos más información.", "set_pendiente_info": True},
            content_type="application/json",
        )
    assert r.status_code == 200
    assert r.get_json()["new_status"] == "pendiente_info"
    with _app.app_context():
        adv = FiscalAdvisoryRequest.query.get(aid)
        assert adv.status == "pendiente_info"
        db.session.remove()


def test_estado_no_cambia_sin_flag(client, _app, advisor_id):
    """Test 9: set_pendiente_info=False mantiene el estado original."""
    aid = _create_advisory(_app, status="submitted")
    _login(client, "advisor_msg@example.com")
    with patch("app._send_advisory_message_email", return_value=True):
        r = client.post(
            f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
            json={"mensaje": "Solo un aviso.", "set_pendiente_info": False},
            content_type="application/json",
        )
    assert r.status_code == 200
    assert r.get_json()["new_status"] == "submitted"
    with _app.app_context():
        adv = FiscalAdvisoryRequest.query.get(aid)
        assert adv.status == "submitted"
        db.session.remove()


def test_mensaje_vacio_devuelve_400(client, _app, advisor_id):
    """Test 10: Mensaje vacío devuelve 400."""
    aid = _create_advisory(_app)
    _login(client, "advisor_msg@example.com")
    r = client.post(
        f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
        json={"mensaje": "   ", "set_pendiente_info": False},
        content_type="application/json",
    )
    assert r.status_code == 400


def test_enviar_presupuesto_sigue_requiriendo_importe(client, _app, advisor_id):
    """Test 11: El flujo de presupuesto existente exige importe >= 1 €."""
    aid = _create_advisory(_app)
    _login(client, "advisor_msg@example.com")
    r = client.post(
        f"/api/admin/asesoramiento/solicitudes/{aid}/enviar-presupuesto",
        json={"message": "Presupuesto sin importe."},
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "Importe" in (r.get_json() or {}).get("error", "")


def test_nota_interna_registrada(client, _app, advisor_id):
    """Test 12: El mensaje se registra en advisory_internal_notes."""
    aid = _create_advisory(_app)
    _login(client, "advisor_msg@example.com")
    texto = "Revisando los exchanges indicados en tu solicitud."
    with patch("app._send_advisory_message_email", return_value=True):
        client.post(
            f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
            json={"mensaje": texto, "set_pendiente_info": False},
            content_type="application/json",
        )
    with _app.app_context():
        nota = AdvisoryInternalNote.query.filter_by(request_id=aid).first()
        assert nota is not None
        assert texto in nota.text
        db.session.remove()


def test_historial_registrado(client, _app, advisor_id):
    """Test 13: Se crea una entrada en fiscal_advisory_status_history."""
    aid = _create_advisory(_app)
    _login(client, "advisor_msg@example.com")
    with patch("app._send_advisory_message_email", return_value=True):
        client.post(
            f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
            json={"mensaje": "Verificando datos.", "set_pendiente_info": False},
            content_type="application/json",
        )
    with _app.app_context():
        historial = FiscalAdvisoryStatusHistory.query.filter_by(request_id=aid).all()
        assert len(historial) >= 1
        notas = [h.note for h in historial if h.note]
        assert any("mensaje" in (n or "").lower() for n in notas)
        db.session.remove()


def test_no_mensaje_en_estado_terminal(client, _app, advisor_id):
    """Test 14: Estado paid_received bloquea el envío de mensaje (409)."""
    aid = _create_advisory(_app, status="paid_received")
    _login(client, "advisor_msg@example.com")
    with patch("app._send_advisory_message_email", return_value=True):
        r = client.post(
            f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje",
            json={"mensaje": "No debería enviarse.", "set_pendiente_info": False},
            content_type="application/json",
        )
    assert r.status_code == 409
