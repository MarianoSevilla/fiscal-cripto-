"""
Tests para DELETE /api/admin/asesoramiento/solicitudes/<id>

Casos cubiertos:
  1. Admin puede borrar solicitud sin pago → 200.
  2. Admin puede borrar solicitud cancelada sin importe → 200.
  3. Usuario normal no puede borrar → 403.
  4. Solicitud con amount_paid > 0 no se puede borrar → 400.
  5. Al borrar se eliminan notas internas asociadas (cascade).
  6. Endpoint devuelve 404 si la solicitud no existe.
  7. La solicitud desaparece de la lista admin tras borrar.
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

from app import app as flask_app, db
from models import User, FiscalAdvisoryRequest, AdvisoryInternalNote


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


# Los fixtures de usuario son de módulo para evitar reuso de IDs en SQLite
# (reusando el mismo id se contaminan los objetos cacheados en el identity map)
@pytest.fixture(scope="module")
def admin_user(_app):
    """Usuario con role='fiscal_advisor' — supera _is_fiscal_advisor(). Único por módulo."""
    with _app.app_context():
        u = User(
            email="admin_adv_test@example.com",
            full_name="Admin Test",
            role="fiscal_advisor",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("admin-pass-test-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        # Limpiar solicitudes huérfanas antes de borrar el usuario
        FiscalAdvisoryRequest.query.filter_by(user_id=uid).delete()
        db.session.commit()
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture(scope="module")
def normal_user(_app):
    """Usuario sin privilegios. Único por módulo."""
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
    """Cliente Flask fresco por test (no comparte cookies entre tests)."""
    return _app.test_client()


def _make_advisory(_app, user_id, amount_paid=None, status="paid_received"):
    """Crea una FiscalAdvisoryRequest de prueba y devuelve su id."""
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


def _login_admin(client):
    r = client.post("/api/login",
                    json={"email": "admin_adv_test@example.com",
                          "password": "admin-pass-test-1234"})
    assert r.status_code == 200, f"Login admin falló: {r.get_json()}"
    return client


def _login_normal(client):
    r = client.post("/api/login",
                    json={"email": "normal_adv_test@example.com",
                          "password": "normal-pass-test-1234"})
    assert r.status_code == 200, f"Login normal falló: {r.get_json()}"
    return client


# ── Tests ────────────────────────────────────────────────────────────────────

def test_admin_puede_borrar_sin_pago(client, admin_user, _app):
    """Admin borra solicitud sin pago → 200 {"ok": True}."""
    adv_id = _make_advisory(_app, admin_user)
    _login_admin(client)
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    data = r.get_json()
    assert r.status_code == 200, data
    assert data.get("ok") is True
    # Verificar que ya no existe en BD
    with _app.app_context():
        assert FiscalAdvisoryRequest.query.get(adv_id) is None


def test_admin_puede_borrar_cancelada_sin_importe(client, admin_user, _app):
    """Admin borra solicitud cancelada (amount_paid=None) → 200."""
    adv_id = _make_advisory(_app, admin_user, amount_paid=None, status="cancelled")
    _login_admin(client)
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    assert r.status_code == 200, r.get_json()
    assert r.get_json().get("ok") is True


def test_usuario_normal_no_puede_borrar(client, normal_user, admin_user, _app):
    """Usuario sin privilegios recibe 403."""
    adv_id = _make_advisory(_app, admin_user)
    _login_normal(client)
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    assert r.status_code == 403
    # Limpiar
    with _app.app_context():
        FiscalAdvisoryRequest.query.filter_by(id=adv_id).delete()
        db.session.commit()


def test_no_borrar_con_pago_registrado(client, admin_user, _app):
    """Solicitud con amount_paid > 0 no puede borrarse → 400."""
    adv_id = _make_advisory(_app, admin_user, amount_paid=4900)  # 49,00 €
    _login_admin(client)
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    data = r.get_json()
    assert r.status_code == 400, data
    assert "pago" in data.get("error", "").lower()
    # Confirmar que sigue existiendo
    with _app.app_context():
        assert FiscalAdvisoryRequest.query.get(adv_id) is not None
        FiscalAdvisoryRequest.query.filter_by(id=adv_id).delete()
        db.session.commit()


def test_borrar_elimina_notas_internas(client, admin_user, _app):
    """Al borrar la solicitud, las notas internas asociadas desaparecen (cascade)."""
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

    _login_admin(client)
    r = client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")
    assert r.status_code == 200, r.get_json()

    with _app.app_context():
        assert FiscalAdvisoryRequest.query.get(adv_id) is None
        assert AdvisoryInternalNote.query.get(nota_id) is None


def test_no_existe_devuelve_404(client, admin_user, _app):
    """Solicitud inexistente devuelve 404."""
    _login_admin(client)
    r = client.delete("/api/admin/asesoramiento/solicitudes/99999")
    assert r.status_code == 404


def test_lista_admin_no_incluye_borrada(client, admin_user, _app):
    """Tras borrar, la solicitud ya no aparece en la lista admin."""
    adv_id = _make_advisory(_app, admin_user)
    _login_admin(client)

    # Verificar que está en lista antes de borrar
    r_antes = client.get("/api/admin/asesoramiento/solicitudes")
    items_antes = r_antes.get_json()
    assert isinstance(items_antes, list), items_antes
    ids_antes = [item["id"] for item in items_antes]
    assert adv_id in ids_antes

    # Borrar
    client.delete(f"/api/admin/asesoramiento/solicitudes/{adv_id}")

    # Verificar que no aparece
    r_despues = client.get("/api/admin/asesoramiento/solicitudes")
    ids_despues = [item["id"] for item in r_despues.get_json()]
    assert adv_id not in ids_despues
