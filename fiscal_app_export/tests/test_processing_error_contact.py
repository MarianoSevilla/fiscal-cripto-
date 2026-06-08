"""
Tests para el flujo de contacto desde errores de procesamiento.

Casos cubiertos:
  1. Admin puede obtener contact-context de un error con email.
  2. Usuario normal recibe 404 en contact-context.
  3. Anónimo recibe redirect en contact-context.
  4. contact-context devuelve 404 si el error no tiene email.
  5. contact-context devuelve 404 si el error no existe.
  6. /api/stats no expone el email real (solo masked) en processing_errors.
  7. /api/stats expone has_contact=True cuando hay email, False cuando no.
  8. /api/stats expone id en processing_errors.
  9. Crear borrador individual via API con individual_email.
 10. Crear borrador individual sin individual_email devuelve 400.
 11. /admin/comunicaciones abre correctamente (admin).
"""

import sys
import os
import tempfile
from datetime import datetime, timezone

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-proc-err-contact")
os.environ["ADMIN_EMAILS"] = "admin_pec@example.com"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User, ProcessingError


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
def admin_user(_app):
    with _app.app_context():
        u = User(
            email="admin_pec@example.com",
            full_name="Admin PEC",
            role="admin",
            email_verified_at=datetime.now(timezone.utc),
        )
        u.set_password("adminpass")
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture(scope="module")
def normal_user(_app):
    with _app.app_context():
        u = User(
            email="user_pec@example.com",
            full_name="User PEC",
            role="user",
            email_verified_at=datetime.now(timezone.utc),
        )
        u.set_password("userpass")
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture(scope="module")
def error_with_email(_app):
    with _app.app_context():
        e = ProcessingError(
            exchange="binance",
            email="victim@example.com",
            error_type="parse_error",
            stage="read_csv",
            message_short="Unexpected column",
            fingerprint="abc12345",
            auto_email_sent=False,
            resolved=False,
        )
        db.session.add(e)
        db.session.commit()
        return e.id


@pytest.fixture(scope="module")
def error_no_email(_app):
    with _app.app_context():
        e = ProcessingError(
            exchange="kraken",
            email=None,
            error_type="unknown",
            stage="init",
            message_short="No context",
            fingerprint="def67890",
            auto_email_sent=False,
            resolved=False,
        )
        db.session.add(e)
        db.session.commit()
        return e.id


@pytest.fixture
def client(_app):
    return _app.test_client()


def _login(client, email, password):
    r = client.post("/api/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login falló ({email}): {r.get_json()}"


# ── Tests: contact-context endpoint ──────────────────────────────────────────

class TestContactContext:
    def test_admin_puede_obtener_context(self, client, admin_user, error_with_email):
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.get(f"/api/admin/processing-errors/{error_with_email}/contact-context")
        assert r.status_code == 200
        data = r.get_json()
        assert data["email"] == "victim@example.com"
        assert "***" in data["email_masked"]
        assert "binance" in data["exchange"]
        assert data["subject"]
        assert data["body"]
        assert "id" in data

    def test_context_tiene_asunto_con_exchange(self, client, admin_user, error_with_email):
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.get(f"/api/admin/processing-errors/{error_with_email}/contact-context")
        data = r.get_json()
        assert "Binance" in data["subject"] or "binance" in data["subject"].lower()

    def test_usuario_normal_recibe_404(self, client, normal_user, error_with_email):
        _login(client, "user_pec@example.com", "userpass")
        r = client.get(f"/api/admin/processing-errors/{error_with_email}/contact-context")
        assert r.status_code == 404

    def test_anonimo_no_puede_acceder(self, client, error_with_email):
        anon = flask_app.test_client()
        r = anon.get(f"/api/admin/processing-errors/{error_with_email}/contact-context")
        assert r.status_code in (302, 401, 404)  # login_required → 401; abort(404) si no admin

    def test_error_sin_email_devuelve_404(self, client, admin_user, error_no_email):
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.get(f"/api/admin/processing-errors/{error_no_email}/contact-context")
        assert r.status_code == 404

    def test_error_inexistente_devuelve_404(self, client, admin_user):
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.get("/api/admin/processing-errors/999999/contact-context")
        assert r.status_code == 404


# ── Tests: /api/stats no expone email real ────────────────────────────────────

class TestStatsEmailMasking:
    def test_stats_email_masked_en_processing_errors(self, client, admin_user, error_with_email):
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.get("/api/stats")
        assert r.status_code == 200
        data = r.get_json()
        errs = data.get("errores", {}).get("processing_errors", [])
        for e in errs:
            assert "victim@example.com" not in (e.get("usuario") or "")

    def test_stats_expone_has_contact_true(self, client, admin_user, _app, error_with_email):
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.get("/api/stats")
        data = r.get_json()
        errs = data.get("errores", {}).get("processing_errors", [])
        matching = [e for e in errs if e.get("id") == error_with_email]
        assert matching, "Error con email no aparece en stats"
        assert matching[0]["has_contact"] is True

    def test_stats_has_contact_false_para_errores_sin_email(self, client, admin_user):
        """Cualquier error sin email en stats debe tener has_contact=False."""
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.get("/api/stats")
        data = r.get_json()
        errs = data.get("errores", {}).get("processing_errors", [])
        # Verificar que ningún error con usuario '—' tiene has_contact=True
        for e in errs:
            if e.get("usuario") == "—":
                assert e.get("has_contact") is False

    def test_stats_expone_id(self, client, admin_user, error_with_email):
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.get("/api/stats")
        data = r.get_json()
        errs = data.get("errores", {}).get("processing_errors", [])
        assert all("id" in e for e in errs)


# ── Tests: borrador individual ────────────────────────────────────────────────

class TestIndividualDraft:
    def test_crear_borrador_individual(self, client, admin_user):
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.post(
            "/api/admin/comunicaciones/drafts",
            json={
                "subject":          "Hemos corregido el problema",
                "body":             "Hola, ya está solucionado.",
                "recipient_segment": "individual",
                "individual_email": "victim@example.com",
            },
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data["recipient_segment"] == "individual"
        assert data["individual_email"] == "victim@example.com"

    def test_borrador_individual_sin_email_devuelve_400(self, client, admin_user):
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.post(
            "/api/admin/comunicaciones/drafts",
            json={
                "subject":          "Test",
                "body":             "Cuerpo.",
                "recipient_segment": "individual",
            },
        )
        assert r.status_code == 400

    def test_usuario_normal_no_puede_crear_borrador(self, client, normal_user):
        _login(client, "user_pec@example.com", "userpass")
        r = client.post(
            "/api/admin/comunicaciones/drafts",
            json={"subject": "X", "body": "Y", "recipient_segment": "all"},
        )
        assert r.status_code == 404

    def test_comunicaciones_page_accesible_admin(self, client, admin_user):
        _login(client, "admin_pec@example.com", "adminpass")
        r = client.get("/admin/comunicaciones")
        assert r.status_code == 200
