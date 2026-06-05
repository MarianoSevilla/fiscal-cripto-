"""
Tests para DELETE /api/admin/asesoramiento/solicitudes/<id>

Casos cubiertos:
  1. Admin puede borrar solicitud sin pago → 200.
  2. Admin puede borrar solicitud cancelada sin importe → 200.
  3. Usuario normal no puede borrar → 403.
  4. Fiscal_advisor no puede borrar → 403.
  5. Admin SÍ puede borrar solicitud con pago registrado → 200 (comportamiento admin).
  6. Al borrar se eliminan notas internas asociadas (cascade).
  7. Endpoint devuelve 404 si la solicitud no existe.
  8. La solicitud desaparece de la lista admin tras borrar.
  9. Se registra entrada en advisory_audit_log al borrar.
"""

import sys
import os
import tempfile
from datetime import datetime

import pytest

# ── Entorno antes de importar app ──────────────────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-adv-delete-only")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app    import app as flask_app, db
from models import User, FiscalAdvisoryRequest, AdvisoryInternalNote, AdvisoryAuditLog


# ── Fixtures ────────────────────────────────────────────────────────────────

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
    """Usuario con role='admin' — único autorizado para borrar solicitudes."""
    with _app.app_context():
        u = User(
            email="admin_adv_test@example.com",
            full_name="Admin Test",
            role="admin",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("admin-pass-test-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        FiscalAdvisoryRequest.query.filter_by(user_id=uid).delete()
        db.session.commit()
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture(scope="module")
def advisor_user(_app):
    """Usuario con role='fiscal_advisor' — NO autorizado para borrar."""
    with _app.app_context():
        u = User(
            email="advisor_adv_test@example.com",
            full_name="Advisor Test",
            role="fiscal_advisor",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("advisor-pass-test-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture(scope="module")
def normal_user(_app):
    """Usuario sin privilegios."""
    with _app.app_context():
        u = User(
            email="normal_adv_test@example.com",
            full_name="Normal Test",
            role="user",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("normal-pass-test-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture
def client(_app):
    return _app.test_client()


@pytest.fixture(autouse=True)
def _clean_login(_app):
    yield
    from flask import g
    g.pop("_login_user", None)


def _make_advisory(_app, user_id, amount_paid=None, status="paid_received"):
    with _app.app_context():
        adv = FiscalAdvisoryRequest(
            user_id               = user_id,
            full_name             = "Test Solicitante",
            email                 = "solicitante@example.com",
            tax_residence_country = "España",
            tax_year              = 2024,
            service_type          = "revision_basica",
            case_description      = "Descripción de prueba para test.",
            status                = status,
            amount_paid           = amount_paid,
        )
        db.session.add(adv)
        db.session.commit()
        return adv.id


def _login(client, email, password):
    r = client.post("/api/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login falló: {r.get_json()}"


# ── Tests ────────────────────────────────────────────────────────────────────

def test_admin_puede_borrar_sin_pago(client, admin_user, _app):
    """Admin borra solicitud sin pago → 200 {"ok": True}."""
    adv_id = _make_advisory(_app, admin_user)
    _login(client, "admin_adv_test@example.com", "admin-pass-test-1234")
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    assert r.status_code == 200, r.get_json()
    assert r.get_json().get("ok") is True
    with _app.app_context():
        assert FiscalAdvisoryRequest.query.get(adv_id) is None


def test_admin_puede_borrar_cancelada_sin_importe(client, admin_user, _app):
    """Admin borra solicitud cancelada (amount_paid=None) → 200."""
    adv_id = _make_advisory(_app, admin_user, amount_paid=None, status="cancelled")
    _login(client, "admin_adv_test@example.com", "admin-pass-test-1234")
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    assert r.status_code == 200, r.get_json()
    assert r.get_json().get("ok") is True


def test_admin_puede_borrar_con_pago(client, admin_user, _app):
    """Admin puede borrar solicitudes con pago registrado → 200 (restricción eliminada)."""
    adv_id = _make_advisory(_app, admin_user, amount_paid=4900, status="paid_received")
    _login(client, "admin_adv_test@example.com", "admin-pass-test-1234")
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    assert r.status_code == 200, r.get_json()
    assert r.get_json().get("ok") is True
    with _app.app_context():
        assert FiscalAdvisoryRequest.query.get(adv_id) is None


def test_usuario_normal_no_puede_borrar(client, normal_user, admin_user, _app):
    """Usuario sin privilegios recibe 403."""
    adv_id = _make_advisory(_app, admin_user)
    _login(client, "normal_adv_test@example.com", "normal-pass-test-1234")
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    assert r.status_code == 403
    with _app.app_context():
        FiscalAdvisoryRequest.query.filter_by(id=adv_id).delete()
        db.session.commit()


def test_fiscal_advisor_no_puede_borrar(client, advisor_user, admin_user, _app):
    """fiscal_advisor recibe 403 al intentar borrar."""
    adv_id = _make_advisory(_app, admin_user)
    _login(client, "advisor_adv_test@example.com", "advisor-pass-test-1234")
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    assert r.status_code == 403, f"Esperado 403, recibido {r.status_code}: {r.get_json()}"
    with _app.app_context():
        # La solicitud sigue existiendo
        assert FiscalAdvisoryRequest.query.get(adv_id) is not None
        FiscalAdvisoryRequest.query.filter_by(id=adv_id).delete()
        db.session.commit()


def test_borrar_elimina_notas_internas(client, admin_user, _app):
    """Al borrar la solicitud, las notas internas desaparecen (cascade)."""
    adv_id = _make_advisory(_app, admin_user)
    with _app.app_context():
        nota = AdvisoryInternalNote(
            request_id  = adv_id,
            author_id   = admin_user,
            author_name = "Admin Test",
            text        = "Nota de prueba.",
        )
        db.session.add(nota)
        db.session.commit()
        nota_id = nota.id

    _login(client, "admin_adv_test@example.com", "admin-pass-test-1234")
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    assert r.status_code == 200, r.get_json()
    with _app.app_context():
        assert FiscalAdvisoryRequest.query.get(adv_id) is None
        assert AdvisoryInternalNote.query.get(nota_id) is None


def test_no_existe_devuelve_404(client, admin_user, _app):
    """Solicitud inexistente devuelve 404."""
    _login(client, "admin_adv_test@example.com", "admin-pass-test-1234")
    r = client.delete("/api/admin/asesoramiento/solicitudes/99999")
    assert r.status_code == 404


def test_lista_admin_no_incluye_borrada(client, admin_user, _app):
    """Tras borrar, la solicitud ya no aparece en la lista admin."""
    adv_id = _make_advisory(_app, admin_user)
    _login(client, "admin_adv_test@example.com", "admin-pass-test-1234")

    r_antes = client.get("/api/admin/asesoramiento/solicitudes")
    ids_antes = [item["id"] for item in r_antes.get_json()]
    assert adv_id in ids_antes

    client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")

    r_despues = client.get("/api/admin/asesoramiento/solicitudes")
    ids_despues = [item["id"] for item in r_despues.get_json()]
    assert adv_id not in ids_despues


def test_audit_log_creado_al_borrar(client, admin_user, _app):
    """Al borrar, se crea una entrada en advisory_audit_log."""
    adv_id = _make_advisory(_app, admin_user, amount_paid=7900, status="completed")
    _login(client, "admin_adv_test@example.com", "admin-pass-test-1234")
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    assert r.status_code == 200
    with _app.app_context():
        log = AdvisoryAuditLog.query.filter_by(
            request_id=adv_id,
            action=AdvisoryAuditLog.ACTION_DELETED,
        ).first()
        assert log is not None
        assert log.admin_id == admin_user
