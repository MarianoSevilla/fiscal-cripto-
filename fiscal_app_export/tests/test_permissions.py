"""
Tests de permisos — Fase 1 del sistema de roles escalable.

Valida que cada combinación de rol/ruta devuelva el código HTTP correcto.
Cubre tres dimensiones:
  1. Rutas protegidas con @login_required (usuario no autenticado → 302 o 401)
  2. Rutas exclusivas de admin (@require_admin / @require_admin_page)
  3. Rutas de asesor fiscal (@require_fiscal_advisor / @require_fiscal_advisor_page)

Roles usados en estos tests:
  - 'user'           → usuario normal
  - 'fiscal_advisor' → asesor fiscal
  - 'admin'          → administrador

La autorización usa el campo `role` de la BD como fuente primaria.
Las variables de entorno ADMIN_EMAILS/FISCAL_ADVISOR_EMAILS se dejan vacías
para verificar que la lógica de rol es suficiente.
"""

import sys
import os
import tempfile
from datetime import datetime

import pytest

# ── Entorno antes de importar app ────────────────────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATABASE_URL"]          = f"sqlite:///{_TEST_DB}"
os.environ["SECRET_KEY"]            = "test-secret-permissions"
os.environ["ADMIN_EMAILS"]          = ""   # sin fallback de email — testar solo roles
os.environ["FISCAL_ADVISOR_EMAILS"] = ""

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User


# ── Fixtures base ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _app():
    """
    Configura la aplicación y la BD para el módulo de tests.

    IMPORTANTE: No mantiene un app_context persistente durante los tests.
    Flask 3.x + Flask-Login 0.6.x almacenan current_user en g._login_user.
    Con un app_context externo abierto, g persiste entre peticiones y el usuario
    autenticado de un cliente "contamina" los clientes anónimos posteriores.
    Cada test_client() gestiona su propio contexto por petición.
    """
    flask_app.config["TESTING"]               = True
    flask_app.config["RATELIMIT_ENABLED"]      = False
    flask_app.config["WTF_CSRF_ENABLED"]       = False
    flask_app.config["SESSION_COOKIE_SECURE"]  = False
    flask_app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {}
    # Crear tablas con contexto puntual — NO mantener el contexto abierto
    with flask_app.app_context():
        db.create_all()
    yield flask_app
    # Limpiar con contexto puntual al finalizar el módulo
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


def _create_user(app, email, role, password="Test-1234-safe"):
    """Crea un usuario en BD dentro de un contexto puntual."""
    with app.app_context():
        u = User(
            email=email,
            full_name=f"Test {role}",
            role=role,
            email_verified_at=datetime.utcnow(),
        )
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture(scope="module")
def user_id(_app):
    uid = _create_user(_app, "perm_user@example.com", "user")
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture(scope="module")
def advisor_id(_app):
    uid = _create_user(_app, "perm_advisor@example.com", "fiscal_advisor")
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture(scope="module")
def admin_id(_app):
    uid = _create_user(_app, "perm_admin@example.com", "admin")
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture
def anon_client(_app):
    """Cliente sin sesión."""
    return _app.test_client()


@pytest.fixture
def user_client(_app, user_id):
    c = _app.test_client()
    r = c.post("/api/login", json={"email": "perm_user@example.com", "password": "Test-1234-safe"})
    assert r.status_code == 200, f"Login user falló: {r.get_json()}"
    return c


@pytest.fixture
def advisor_client(_app, advisor_id):
    c = _app.test_client()
    r = c.post("/api/login", json={"email": "perm_advisor@example.com", "password": "Test-1234-safe"})
    assert r.status_code == 200, f"Login advisor falló: {r.get_json()}"
    return c


@pytest.fixture
def admin_client(_app, admin_id):
    c = _app.test_client()
    r = c.post("/api/login", json={"email": "perm_admin@example.com", "password": "Test-1234-safe"})
    assert r.status_code == 200, f"Login admin falló: {r.get_json()}"
    return c


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_redirect_to_login(response):
    """Devuelve True si es un redirect 302 hacia /login/."""
    if response.status_code == 302:
        loc = response.headers.get("Location", "")
        return "/login" in loc or loc == "/"
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# 1. RUTAS CON @login_required — usuario no autenticado
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoginRequired:
    """Páginas que requieren autenticación devuelven redirect o 401 para anon."""

    @pytest.mark.parametrize("url", [
        "/dashboard",
        "/modelo721",
        "/account",
    ])
    def test_anon_redirige_al_login(self, anon_client, url):
        r = anon_client.get(url)
        assert r.status_code in (302, 401), (
            f"{url}: anon debería obtener 302/401, obtuvo {r.status_code}"
        )

    @pytest.mark.parametrize("url", [
        "/dashboard",
        "/modelo721",
        "/account",
    ])
    def test_user_autenticado_puede_acceder(self, user_client, url):
        r = user_client.get(url)
        assert r.status_code == 200, (
            f"{url}: user debería obtener 200, obtuvo {r.status_code}"
        )

    @pytest.mark.parametrize("url", [
        "/dashboard",
        "/modelo721",
        "/account",
    ])
    def test_advisor_puede_acceder(self, advisor_client, url):
        r = advisor_client.get(url)
        assert r.status_code == 200

    @pytest.mark.parametrize("url", [
        "/dashboard",
        "/modelo721",
        "/account",
    ])
    def test_admin_puede_acceder(self, admin_client, url):
        r = admin_client.get(url)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PANEL DE ASESORAMIENTO (@require_fiscal_advisor)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAsesoramientoAccess:
    """Solo fiscal_advisor y admin pueden acceder al panel de asesoramiento."""

    def test_anon_no_puede_acceder_pagina(self, anon_client):
        r = anon_client.get("/admin/asesoramiento")
        assert r.status_code in (302, 401)

    def test_user_no_puede_acceder_pagina(self, user_client):
        r = user_client.get("/admin/asesoramiento")
        # @require_fiscal_advisor_page redirige a /dashboard
        assert r.status_code == 302
        assert "/dashboard" in r.headers.get("Location", "")

    def test_advisor_puede_acceder_pagina(self, advisor_client):
        r = advisor_client.get("/admin/asesoramiento")
        assert r.status_code == 200

    def test_admin_puede_acceder_pagina(self, admin_client):
        r = admin_client.get("/admin/asesoramiento")
        assert r.status_code == 200

    # APIs de asesoramiento

    def test_user_no_puede_listar_solicitudes(self, user_client):
        r = user_client.get("/api/admin/asesoramiento/solicitudes")
        assert r.status_code == 403

    def test_advisor_puede_listar_solicitudes(self, advisor_client):
        r = advisor_client.get("/api/admin/asesoramiento/solicitudes")
        assert r.status_code == 200

    def test_admin_puede_listar_solicitudes(self, admin_client):
        r = admin_client.get("/api/admin/asesoramiento/solicitudes")
        assert r.status_code == 200

    def test_anon_no_puede_listar_solicitudes(self, anon_client):
        r = anon_client.get("/api/admin/asesoramiento/solicitudes")
        assert r.status_code in (302, 401)

    def test_user_no_puede_cambiar_estado(self, user_client):
        r = user_client.post("/api/admin/asesoramiento/solicitudes/99999/estado",
                             json={"status": "in_progress"})
        assert r.status_code == 403

    def test_advisor_recibe_404_en_solicitud_inexistente(self, advisor_client):
        # Autorizado pero la solicitud no existe → 404 (no 403)
        r = advisor_client.get("/api/admin/asesoramiento/solicitudes/99999")
        assert r.status_code == 404

    def test_user_recibe_403_en_solicitud_inexistente(self, user_client):
        # No autorizado → 403 antes de buscar en BD
        r = user_client.get("/api/admin/asesoramiento/solicitudes/99999")
        assert r.status_code == 403

    def test_user_no_puede_enviar_presupuesto(self, user_client):
        r = user_client.post(
            "/api/admin/asesoramiento/solicitudes/99999/enviar-presupuesto",
            json={"amount_euros": "100"},
        )
        assert r.status_code == 403

    def test_user_no_puede_anadir_nota(self, user_client):
        r = user_client.post("/api/admin/asesoramiento/solicitudes/99999/nota",
                             json={"nota": "hola"})
        assert r.status_code == 403

    def test_user_no_puede_borrar_solicitud(self, user_client):
        r = user_client.delete("/api/admin/asesoramiento/solicitudes/99999")
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PANEL DE RECURSOS (@require_fiscal_advisor)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecursosAccess:
    """Solo fiscal_advisor y admin pueden acceder al panel de recursos."""

    def test_user_no_puede_acceder_pagina(self, user_client):
        r = user_client.get("/admin/recursos")
        assert r.status_code == 302
        assert "/dashboard" in r.headers.get("Location", "")

    def test_advisor_puede_acceder_pagina(self, advisor_client):
        r = advisor_client.get("/admin/recursos")
        assert r.status_code == 200

    def test_admin_puede_acceder_pagina(self, admin_client):
        r = admin_client.get("/admin/recursos")
        assert r.status_code == 200

    def test_user_no_puede_listar_recursos(self, user_client):
        r = user_client.get("/api/admin/recursos/solicitudes")
        assert r.status_code == 403

    def test_advisor_puede_listar_recursos(self, advisor_client):
        r = advisor_client.get("/api/admin/recursos/solicitudes")
        assert r.status_code == 200

    def test_admin_puede_listar_recursos(self, admin_client):
        r = admin_client.get("/api/admin/recursos/solicitudes")
        assert r.status_code == 200

    def test_user_no_puede_cambiar_estado_recurso(self, user_client):
        r = user_client.post("/api/admin/recursos/solicitudes/99999/estado",
                             json={"status": "sent"})
        assert r.status_code == 403

    def test_user_no_puede_anadir_nota_recurso(self, user_client):
        r = user_client.post("/api/admin/recursos/solicitudes/99999/nota",
                             json={"nota": "test"})
        assert r.status_code == 403

    def test_user_no_puede_borrar_recurso(self, user_client):
        r = user_client.delete("/api/admin/recursos/solicitudes/99999")
        assert r.status_code == 403

    def test_advisor_recibe_404_en_recurso_inexistente(self, advisor_client):
        r = advisor_client.get("/api/admin/recursos/solicitudes/99999")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 4. STATS Y CONTACTOS (@require_admin — solo admin)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdminOnlyAccess:
    """Stats y contactos son exclusivos de admin; advisor NO tiene acceso."""

    # /stats (página HTML)
    def test_anon_no_puede_ver_stats(self, anon_client):
        r = anon_client.get("/stats")
        assert r.status_code in (302, 401)

    def test_user_redirige_en_stats(self, user_client):
        r = user_client.get("/stats")
        assert r.status_code == 302
        assert "/dashboard" in r.headers.get("Location", "")

    def test_advisor_redirige_en_stats(self, advisor_client):
        """El advisor NO tiene acceso a stats."""
        r = advisor_client.get("/stats")
        assert r.status_code == 302
        assert "/dashboard" in r.headers.get("Location", "")

    def test_admin_puede_ver_stats(self, admin_client):
        r = admin_client.get("/stats")
        assert r.status_code == 200

    # /api/stats
    def test_user_no_puede_api_stats(self, user_client):
        r = user_client.get("/api/stats")
        assert r.status_code == 403

    def test_advisor_no_puede_api_stats(self, advisor_client):
        """El advisor NO tiene acceso a /api/stats."""
        r = advisor_client.get("/api/stats")
        assert r.status_code == 403

    def test_admin_puede_api_stats(self, admin_client):
        r = admin_client.get("/api/stats")
        assert r.status_code == 200

    # /admin/contactos (página)
    def test_user_redirige_en_contactos(self, user_client):
        r = user_client.get("/admin/contactos")
        assert r.status_code == 302

    def test_advisor_redirige_en_contactos(self, advisor_client):
        """El advisor NO tiene acceso al panel de contactos."""
        r = advisor_client.get("/admin/contactos")
        assert r.status_code == 302
        assert "/dashboard" in r.headers.get("Location", "")

    def test_admin_puede_ver_contactos(self, admin_client):
        r = admin_client.get("/admin/contactos")
        assert r.status_code == 200

    # /api/admin/contactos
    def test_user_no_puede_api_contactos(self, user_client):
        r = user_client.get("/api/admin/contactos")
        assert r.status_code == 403

    def test_advisor_no_puede_api_contactos(self, advisor_client):
        r = advisor_client.get("/api/admin/contactos")
        assert r.status_code == 403

    def test_admin_puede_api_contactos(self, admin_client):
        r = admin_client.get("/api/admin/contactos")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 5. COMUNICACIONES (@require_admin — abort 404, comportamiento preservado)
# ═══════════════════════════════════════════════════════════════════════════════

class TestComunicacionesAccess:
    """El blueprint de comunicaciones usa abort(404) para ocultar la existencia."""

    def test_anon_no_puede_ver_comunicaciones(self, anon_client):
        r = anon_client.get("/admin/comunicaciones")
        # Sin sesión → redirect al login (login_required actúa antes de abort 404)
        assert r.status_code in (302, 401)

    def test_user_recibe_404_en_comunicaciones(self, user_client):
        r = user_client.get("/admin/comunicaciones")
        assert r.status_code == 404

    def test_advisor_recibe_404_en_comunicaciones(self, advisor_client):
        """El advisor NO tiene acceso a comunicaciones."""
        r = advisor_client.get("/admin/comunicaciones")
        assert r.status_code == 404

    def test_admin_puede_ver_comunicaciones(self, admin_client):
        r = admin_client.get("/admin/comunicaciones")
        assert r.status_code == 200

    def test_user_recibe_404_en_api_campaigns(self, user_client):
        r = user_client.get("/api/admin/comunicaciones/campaigns")
        assert r.status_code == 404

    def test_advisor_recibe_404_en_api_campaigns(self, advisor_client):
        r = advisor_client.get("/api/admin/comunicaciones/campaigns")
        assert r.status_code == 404

    def test_admin_puede_ver_api_campaigns(self, admin_client):
        r = admin_client.get("/api/admin/comunicaciones/campaigns")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MIS SOLICITUDES FISCALES (admin-only, abort 404)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMisSolicitudesFiscales:
    """/mis-solicitudes-fiscales solo accesible para admin; devuelve 404 al resto."""

    def test_anon_redirige(self, anon_client):
        r = anon_client.get("/mis-solicitudes-fiscales")
        assert r.status_code in (302, 401)

    def test_user_recibe_404(self, user_client):
        r = user_client.get("/mis-solicitudes-fiscales")
        assert r.status_code == 404

    def test_advisor_recibe_404(self, advisor_client):
        """Advisor no ve esta página — devuelve 404."""
        r = advisor_client.get("/mis-solicitudes-fiscales")
        assert r.status_code == 404

    def test_admin_puede_acceder(self, admin_client):
        r = admin_client.get("/mis-solicitudes-fiscales")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 7. AISLAMIENTO DE DATOS — API mis-solicitudes (usuario normal)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAislamiento:
    """Cada usuario solo ve sus propios datos en endpoints user-scoped."""

    def test_user_puede_ver_sus_solicitudes(self, user_client):
        r = user_client.get("/api/asesoramiento/mis-solicitudes")
        assert r.status_code == 200
        # Lista vacía o con sus propias solicitudes (sin datos de otros usuarios)
        data = r.get_json()
        assert isinstance(data, list)

    def test_advisor_puede_ver_sus_solicitudes(self, advisor_client):
        r = advisor_client.get("/api/asesoramiento/mis-solicitudes")
        assert r.status_code == 200

    def test_anon_no_puede_ver_mis_solicitudes(self, anon_client):
        r = anon_client.get("/api/asesoramiento/mis-solicitudes")
        assert r.status_code in (302, 401)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. FALLBACK DE EMAIL (env var como respaldo)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmailFallback:
    """
    Verifica que el fallback de ADMIN_EMAILS funciona para usuarios con role='user'
    cuyo email está en la variable de entorno.
    Esta es la compatibilidad hacia atrás que se mantiene en Fase 1.
    """

    def test_user_con_email_admin_tiene_acceso_admin(self, _app):
        """Un usuario con role='user' pero email en ADMIN_EMAILS actúa como admin."""
        import auth as auth_module

        email = "fallback_admin@example.com"

        # Parchar el frozenset de auth.py para este test
        original = auth_module.ADMIN_EMAILS
        try:
            auth_module.ADMIN_EMAILS = frozenset([email])

            _create_user(_app, email, "user", "Fallback-1234")
            # Cada petición usa su propio contexto — NO abrir app_context externo
            c = _app.test_client()
            r = c.post("/api/login", json={"email": email, "password": "Fallback-1234"})
            assert r.status_code == 200

            r2 = c.get("/api/stats")
            assert r2.status_code == 200, (
                "Usuario con role='user' pero email en ADMIN_EMAILS debería acceder a /api/stats"
            )
        finally:
            auth_module.ADMIN_EMAILS = original
            with _app.app_context():
                User.query.filter_by(email=email).delete()
                db.session.commit()
