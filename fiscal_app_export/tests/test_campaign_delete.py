"""
Tests para DELETE /api/admin/comunicaciones/campaigns/<id>

Casos cubiertos:
  1. Admin puede borrar borrador (draft).
  2. Admin puede borrar campaña fallida (failed).
  3. Admin puede borrar campaña 'sent' SIN entregas reales.
  4. No se puede borrar campaña 'sent' con entregas status='sent'.
  5. No se puede borrar campaña en estado 'sending'.
  6. Al borrar se eliminan las CommunicationDelivery asociadas.
  7. Usuario normal recibe 404 (no admin).
  8. Campaña inexistente devuelve 404.
  9. La campaña ya no aparece en la lista tras borrar.
"""

import sys
import os
import tempfile
from datetime import datetime

import pytest

# ── Entorno — debe setearse ANTES de importar app ─────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-campaign-delete-only")
# _is_admin() en communications/routes.py comprueba ADMIN_EMAILS en el env.
# Debe estar fijado antes de que el módulo se importe.
os.environ["ADMIN_EMAILS"] = "admin_del_test@example.com"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User, CommunicationCampaign, CommunicationDelivery


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


@pytest.fixture(scope="module")
def admin_user(_app):
    """Usuario cuyo email está en ADMIN_EMAILS → supera _is_admin()."""
    with _app.app_context():
        u = User(
            email="admin_del_test@example.com",
            full_name="Admin Delete Test",
            role="user",                      # rol no importa — ADMIN_EMAILS manda
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("admin-del-pass-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        CommunicationCampaign.query.filter_by(created_by_id=uid).delete()
        db.session.commit()
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture(scope="module")
def normal_user(_app):
    """Usuario sin privilegios de admin."""
    with _app.app_context():
        u = User(
            email="normal_del_test@example.com",
            full_name="Normal Delete Test",
            role="user",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("normal-del-pass-1234")
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_campaign(_app, creator_id, status="draft", recipients_count=0):
    """Crea una CommunicationCampaign directamente en BD."""
    with _app.app_context():
        c = CommunicationCampaign(
            subject          = f"Test campaña [{status}]",
            body             = "Cuerpo de test.",
            status           = status,
            created_by_id    = creator_id,
            recipients_count = recipients_count,
        )
        db.session.add(c)
        db.session.commit()
        return c.id


def _make_delivery(_app, campaign_id, status="sent"):
    """Añade una CommunicationDelivery a una campaña."""
    with _app.app_context():
        d = CommunicationDelivery(
            campaign_id = campaign_id,
            email       = "destinatario@example.com",
            status      = status,
        )
        db.session.add(d)
        db.session.commit()
        return d.id


def _login_admin(client):
    r = client.post("/api/login",
                    json={"email": "admin_del_test@example.com",
                          "password": "admin-del-pass-1234"})
    assert r.status_code == 200, f"Login admin falló: {r.get_json()}"
    return client


def _login_normal(client):
    r = client.post("/api/login",
                    json={"email": "normal_del_test@example.com",
                          "password": "normal-del-pass-1234"})
    assert r.status_code == 200, f"Login normal falló: {r.get_json()}"
    return client


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_admin_puede_borrar_draft(client, admin_user, _app):
    """Admin borra borrador → 200 {ok: true}; desaparece de BD."""
    cid = _make_campaign(_app, admin_user, status="draft")
    _login_admin(client)
    r = client.delete(f"/api/admin/comunicaciones/campaigns/{cid}")
    data = r.get_json()
    assert r.status_code == 200, data
    assert data.get("ok") is True
    with _app.app_context():
        assert CommunicationCampaign.query.get(cid) is None


def test_admin_puede_borrar_failed(client, admin_user, _app):
    """Admin borra campaña fallida → 200."""
    cid = _make_campaign(_app, admin_user, status="failed")
    _login_admin(client)
    r = client.delete(f"/api/admin/comunicaciones/campaigns/{cid}")
    assert r.status_code == 200, r.get_json()
    assert r.get_json().get("ok") is True
    with _app.app_context():
        assert CommunicationCampaign.query.get(cid) is None


def test_admin_puede_borrar_sent_sin_entregas_reales(client, admin_user, _app):
    """
    Campaña 'sent' con recipients_count=0 y sin deliveries status='sent'
    → borrable (test/empty run).
    """
    cid = _make_campaign(_app, admin_user, status="sent", recipients_count=0)
    # delivery fallida — no cuenta como "real"
    _make_delivery(_app, cid, status="failed")
    _login_admin(client)
    r = client.delete(f"/api/admin/comunicaciones/campaigns/{cid}")
    assert r.status_code == 200, r.get_json()
    assert r.get_json().get("ok") is True
    with _app.app_context():
        assert CommunicationCampaign.query.get(cid) is None
        # La delivery también debe haber sido eliminada
        assert CommunicationDelivery.query.filter_by(campaign_id=cid).count() == 0


def test_no_borrar_sent_con_entregas_reales(client, admin_user, _app):
    """
    Campaña 'sent' con al menos una delivery status='sent'
    → 409, error de trazabilidad.
    """
    cid = _make_campaign(_app, admin_user, status="sent", recipients_count=1)
    _make_delivery(_app, cid, status="sent")
    _login_admin(client)
    r = client.delete(f"/api/admin/comunicaciones/campaigns/{cid}")
    data = r.get_json()
    assert r.status_code == 409, data
    assert data.get("ok") is False
    assert "trazabilidad" in data.get("error", "").lower()
    # Confirmar que la campaña sigue en BD
    with _app.app_context():
        assert CommunicationCampaign.query.get(cid) is not None
        # Limpieza manual
        CommunicationDelivery.query.filter_by(campaign_id=cid).delete()
        CommunicationCampaign.query.filter_by(id=cid).delete()
        db.session.commit()


def test_no_borrar_sending(client, admin_user, _app):
    """Campaña en estado 'sending' no se puede eliminar → 409."""
    cid = _make_campaign(_app, admin_user, status="sending")
    _login_admin(client)
    r = client.delete(f"/api/admin/comunicaciones/campaigns/{cid}")
    data = r.get_json()
    assert r.status_code == 409, data
    assert data.get("ok") is False
    assert "sending" in data.get("error", "").lower()
    with _app.app_context():
        assert CommunicationCampaign.query.get(cid) is not None
        CommunicationCampaign.query.filter_by(id=cid).delete()
        db.session.commit()


def test_borrar_elimina_deliveries(client, admin_user, _app):
    """Al borrar campaña se eliminan todas sus CommunicationDelivery."""
    cid = _make_campaign(_app, admin_user, status="failed")
    did1 = _make_delivery(_app, cid, status="failed")
    did2 = _make_delivery(_app, cid, status="pending")
    _login_admin(client)
    r = client.delete(f"/api/admin/comunicaciones/campaigns/{cid}")
    assert r.status_code == 200, r.get_json()
    with _app.app_context():
        assert CommunicationCampaign.query.get(cid)   is None
        assert CommunicationDelivery.query.get(did1)  is None
        assert CommunicationDelivery.query.get(did2)  is None


def test_usuario_normal_no_puede_borrar(client, normal_user, admin_user, _app):
    """Usuario sin privilegios recibe 404 (no admin)."""
    cid = _make_campaign(_app, admin_user, status="draft")
    _login_normal(client)
    r = client.delete(f"/api/admin/comunicaciones/campaigns/{cid}")
    assert r.status_code == 404
    # Limpieza
    with _app.app_context():
        CommunicationCampaign.query.filter_by(id=cid).delete()
        db.session.commit()


def test_campaña_inexistente_devuelve_404(client, admin_user, _app):
    """ID que no existe → 404."""
    _login_admin(client)
    r = client.delete("/api/admin/comunicaciones/campaigns/99999")
    assert r.status_code == 404


def test_lista_no_incluye_campaña_borrada(client, admin_user, _app):
    """Tras borrar, la campaña no aparece en /api/admin/comunicaciones/campaigns."""
    cid = _make_campaign(_app, admin_user, status="draft")
    _login_admin(client)

    r_antes = client.get("/api/admin/comunicaciones/campaigns")
    ids_antes = [c["id"] for c in r_antes.get_json()]
    assert cid in ids_antes

    client.delete(f"/api/admin/comunicaciones/campaigns/{cid}")

    r_despues = client.get("/api/admin/comunicaciones/campaigns")
    ids_despues = [c["id"] for c in r_despues.get_json()]
    assert cid not in ids_despues
