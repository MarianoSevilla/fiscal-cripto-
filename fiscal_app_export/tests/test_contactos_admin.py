"""
Tests para gestión admin de contactos.

Casos cubiertos:
  1. Contactos archivados NO cuentan en /api/stats (total, nuevos, respondidos, por_tipo).
  2. Contactos no archivados SÍ cuentan en /api/stats.
  3. Admin puede archivar un contacto (PATCH accion=archivar).
  4. Admin puede desarchivar un contacto (PATCH accion=desarchivar).
  5. Admin puede marcar como respondido (PATCH accion=responder).
  6. Usuario normal recibe 403 en GET y PATCH admin.
  7. Contacto archivado sigue existiendo en DB (no borrado físico).
  8. Acción no reconocida devuelve 400.
  9. Contacto inexistente devuelve 404.
 10. GET lista por defecto solo devuelve no archivados; con ?archivados=1 los incluye.
"""

import sys
import os
import tempfile
from datetime import datetime

import pytest

# ── Entorno antes de importar app ──────────────────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-contactos-admin")
os.environ["ADMIN_EMAILS"] = "admin_c_test@example.com"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User, Contacto


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
    with _app.app_context():
        u = User(
            email="admin_c_test@example.com",
            full_name="Admin Contactos Test",
            role="user",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("admin-c-pass-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture(scope="module")
def normal_user(_app):
    with _app.app_context():
        u = User(
            email="normal_c_test@example.com",
            full_name="Normal Contactos Test",
            role="user",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("normal-c-pass-1234")
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


def _login_admin(client):
    r = client.post("/api/login",
                    json={"email": "admin_c_test@example.com",
                          "password": "admin-c-pass-1234"})
    assert r.status_code == 200, f"Login admin falló: {r.get_json()}"
    return client


def _login_normal(client):
    r = client.post("/api/login",
                    json={"email": "normal_c_test@example.com",
                          "password": "normal-c-pass-1234"})
    assert r.status_code == 200, f"Login normal falló: {r.get_json()}"
    return client


def _make_contacto(_app, nombre="Test User", archived=False, estado="nuevo", tipo="otro"):
    with _app.app_context():
        c = Contacto(
            nombre=nombre,
            email="test@example.com",
            tipo_consulta=tipo,
            mensaje="Mensaje de prueba.",
            estado=estado,
            archived_at=datetime.utcnow() if archived else None,
        )
        db.session.add(c)
        db.session.commit()
        return c.id


# ── Tests stats ──────────────────────────────────────────────────────────────

def test_stats_no_cuenta_archivados(client, admin_user, _app):
    """Contactos con archived_at != NULL no aparecen en /api/stats."""
    cid_arch   = _make_contacto(_app, nombre="Archivado", archived=True)
    cid_activo = _make_contacto(_app, nombre="Activo",    archived=False)

    _login_admin(client)
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.get_json()
    total = data["contactos"]["total"]

    # El archivado no debe sumar; el activo sí. No podemos asumir que la DB
    # esté vacía (otros tests pueden haber añadido contactos activos), así que
    # verificamos que el archivado NO incrementó el total comparando con/sin él.

    # Archivar el activo y relanzar → total debe bajar en 1
    with _app.app_context():
        c = Contacto.query.get(cid_activo)
        c.archived_at = datetime.utcnow()
        db.session.commit()

    r2 = client.get("/api/stats")
    total2 = r2.get_json()["contactos"]["total"]
    assert total2 == total - 1

    # Limpieza
    with _app.app_context():
        Contacto.query.filter(Contacto.id.in_([cid_arch, cid_activo])).delete()
        db.session.commit()


def test_stats_cuenta_no_archivados(client, admin_user, _app):
    """Contacto activo incrementa el total en /api/stats."""
    _login_admin(client)
    r_antes = client.get("/api/stats")
    total_antes = r_antes.get_json()["contactos"]["total"]

    cid = _make_contacto(_app, nombre="Nuevo activo", archived=False)

    r_despues = client.get("/api/stats")
    total_despues = r_despues.get_json()["contactos"]["total"]
    assert total_despues == total_antes + 1

    with _app.app_context():
        Contacto.query.filter_by(id=cid).delete()
        db.session.commit()


def test_stats_nuevos_excluye_archivados(client, admin_user, _app):
    """contactos.nuevos en stats no incluye archivados con estado='nuevo'."""
    _login_admin(client)
    r_antes = client.get("/api/stats")
    nuevos_antes = r_antes.get_json()["contactos"]["nuevos"]

    cid = _make_contacto(_app, archived=True, estado="nuevo")

    r_despues = client.get("/api/stats")
    nuevos_despues = r_despues.get_json()["contactos"]["nuevos"]
    assert nuevos_despues == nuevos_antes

    with _app.app_context():
        Contacto.query.filter_by(id=cid).delete()
        db.session.commit()


def test_stats_respondidos_excluye_archivados(client, admin_user, _app):
    """contactos.respondidos en stats no incluye archivados con estado='respondido'."""
    _login_admin(client)
    r_antes = client.get("/api/stats")
    resp_antes = r_antes.get_json()["contactos"]["respondidos"]

    cid = _make_contacto(_app, archived=True, estado="respondido")

    r_despues = client.get("/api/stats")
    resp_despues = r_despues.get_json()["contactos"]["respondidos"]
    assert resp_despues == resp_antes

    with _app.app_context():
        Contacto.query.filter_by(id=cid).delete()
        db.session.commit()


# ── Tests PATCH admin ────────────────────────────────────────────────────────

def test_admin_puede_archivar(client, admin_user, _app):
    """Admin archiva contacto → archived_at se rellena."""
    cid = _make_contacto(_app, archived=False)
    _login_admin(client)
    r = client.patch(f"/api/admin/contactos/{cid}", json={"accion": "archivar"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["archived_at"] is not None

    with _app.app_context():
        c = Contacto.query.get(cid)
        assert c.archived_at is not None
        db.session.delete(c)
        db.session.commit()


def test_admin_puede_desarchivar(client, admin_user, _app):
    """Admin desarchiva contacto → archived_at vuelve a NULL."""
    cid = _make_contacto(_app, archived=True)
    _login_admin(client)
    r = client.patch(f"/api/admin/contactos/{cid}", json={"accion": "desarchivar"})
    assert r.status_code == 200
    assert r.get_json()["archived_at"] is None

    with _app.app_context():
        c = Contacto.query.get(cid)
        assert c.archived_at is None
        db.session.delete(c)
        db.session.commit()


def test_admin_puede_marcar_respondido(client, admin_user, _app):
    """Admin marca contacto como respondido → estado='respondido'."""
    cid = _make_contacto(_app, estado="nuevo")
    _login_admin(client)
    r = client.patch(f"/api/admin/contactos/{cid}", json={"accion": "responder"})
    assert r.status_code == 200
    assert r.get_json()["estado"] == "respondido"

    with _app.app_context():
        c = Contacto.query.get(cid)
        assert c.estado == "respondido"
        db.session.delete(c)
        db.session.commit()


def test_usuario_normal_no_puede_patch(client, normal_user, _app):
    """Usuario normal recibe 403 en PATCH."""
    cid = _make_contacto(_app)
    _login_normal(client)
    r = client.patch(f"/api/admin/contactos/{cid}", json={"accion": "archivar"})
    assert r.status_code == 403

    with _app.app_context():
        Contacto.query.filter_by(id=cid).delete()
        db.session.commit()


def test_usuario_normal_no_puede_get_lista(client, normal_user, _app):
    """Usuario normal recibe 403 en GET lista."""
    _login_normal(client)
    r = client.get("/api/admin/contactos")
    assert r.status_code == 403


def test_archivado_sigue_existiendo_en_db(client, admin_user, _app):
    """Archivar no borra físicamente el registro."""
    cid = _make_contacto(_app)
    _login_admin(client)
    client.patch(f"/api/admin/contactos/{cid}", json={"accion": "archivar"})

    with _app.app_context():
        c = Contacto.query.get(cid)
        assert c is not None
        assert c.archived_at is not None
        db.session.delete(c)
        db.session.commit()


def test_accion_no_reconocida_devuelve_400(client, admin_user, _app):
    """Acción inválida devuelve 400."""
    cid = _make_contacto(_app)
    _login_admin(client)
    r = client.patch(f"/api/admin/contactos/{cid}", json={"accion": "borrar_todo"})
    assert r.status_code == 400

    with _app.app_context():
        Contacto.query.filter_by(id=cid).delete()
        db.session.commit()


def test_contacto_inexistente_devuelve_404(client, admin_user, _app):
    """PATCH con id inexistente devuelve 404."""
    _login_admin(client)
    r = client.patch("/api/admin/contactos/99999", json={"accion": "archivar"})
    assert r.status_code == 404


# ── Tests GET lista ──────────────────────────────────────────────────────────

def test_get_lista_excluye_archivados_por_defecto(client, admin_user, _app):
    """GET /api/admin/contactos sin params no incluye archivados."""
    cid_arch   = _make_contacto(_app, nombre="Arch lista", archived=True)
    cid_activo = _make_contacto(_app, nombre="Activo lista", archived=False)

    _login_admin(client)
    r = client.get("/api/admin/contactos")
    assert r.status_code == 200
    ids = [c["id"] for c in r.get_json()]
    assert cid_activo in ids
    assert cid_arch not in ids

    with _app.app_context():
        Contacto.query.filter(Contacto.id.in_([cid_arch, cid_activo])).delete()
        db.session.commit()


def test_get_lista_incluye_archivados_con_param(client, admin_user, _app):
    """GET /api/admin/contactos?archivados=1 incluye archivados."""
    cid_arch = _make_contacto(_app, nombre="Arch param", archived=True)

    _login_admin(client)
    r = client.get("/api/admin/contactos?archivados=1")
    assert r.status_code == 200
    ids = [c["id"] for c in r.get_json()]
    assert cid_arch in ids

    with _app.app_context():
        Contacto.query.filter_by(id=cid_arch).delete()
        db.session.commit()


# ── Tests página HTML /admin/contactos ───────────────────────────────────────

def test_admin_page_accesible_para_admin(client, admin_user, _app):
    """/admin/contactos devuelve 200 para admin."""
    _login_admin(client)
    r = client.get("/admin/contactos")
    assert r.status_code == 200
    assert b"admin-contactos" in r.data or b"contactos" in r.data.lower()


def test_admin_page_redirige_usuario_normal(client, normal_user, _app):
    """/admin/contactos redirige a /dashboard para usuario sin privilegios."""
    _login_normal(client)
    r = client.get("/admin/contactos")
    assert r.status_code in (302, 403)
    if r.status_code == 302:
        assert b"/dashboard" in r.data or r.location.endswith("/dashboard")


def test_admin_page_sin_sesion_redirige_login(client, _app):
    """/admin/contactos sin sesión redirige al login."""
    r = client.get("/admin/contactos")
    assert r.status_code in (302, 401)


def test_respuesta_api_incluye_campos_requeridos(client, admin_user, _app):
    """Cada item del GET /api/admin/contactos tiene los campos esperados por la UI."""
    cid = _make_contacto(_app, nombre="Campo test")
    _login_admin(client)
    r = client.get("/api/admin/contactos")
    assert r.status_code == 200
    items = r.get_json()
    item  = next((c for c in items if c["id"] == cid), None)
    assert item is not None
    for campo in ("id", "created_at", "nombre", "email_mask", "tipo_consulta",
                  "estado", "archived_at", "mensaje_corto"):
        assert campo in item, f"Falta campo '{campo}' en respuesta API"

    with _app.app_context():
        Contacto.query.filter_by(id=cid).delete()
        db.session.commit()
