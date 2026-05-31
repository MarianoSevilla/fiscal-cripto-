"""
Tests para la Biblioteca de Recursos — Fase 1

Casos cubiertos:
  1. POST /api/recursos/solicitar con datos válidos → 201, registro creado, status=recibido
  2. POST /api/recursos/solicitar sin legal_accepted → 400
  3. POST /api/recursos/solicitar con email inválido → 400
  4. POST /api/recursos/solicitar sin nombre → 400
  5. POST /api/recursos/solicitar con resource_id inexistente → 404
  6. POST /api/recursos/solicitar sin UID ni uid_unknown → 201, status=recibido
  7. GET  /api/admin/recursos/solicitudes sin login → 401
  8. GET  /api/admin/recursos/solicitudes con admin → 200, incluye la solicitud
  9. POST /api/admin/recursos/solicitudes/<id>/estado → actualiza estado
  10. POST /api/admin/recursos/solicitudes/<id>/nota → guarda nota
  11. to_dict() basic y full no fallan
  12. Plantillas de email no lanzan excepción
  13. GET  /recursos → 200 (página pública)
  14. GET  /recursos/<slug> → 200 (página individual)
  15. GET  /recursos/no-existe → 404
"""

import sys
import os
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-resources-1234")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app    import app as flask_app, db
from models import User, Resource, ResourceRequest


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
def resource(_app):
    """Recurso de prueba en BD."""
    with _app.app_context():
        r = Resource(
            slug                          = "test-resource",
            title                         = "Test Resource",
            headline                      = "Titular de prueba",
            subtitle                      = "Subtítulo de prueba",
            description                   = "Descripción breve.",
            what_you_get                  = "- Item 1\n- Item 2",
            requirements                  = "- Requisito A\n- Requisito B",
            cta_text                      = "Solicitar",
            category                      = "bitcoin",
            resource_type                 = "dossier",
            interest_category             = "bitcoin",
            is_active                     = True,
            requires_request              = True,
            requires_affiliate_validation = True,
        )
        db.session.add(r)
        db.session.commit()
        rid = r.id
        db.session.remove()
    yield rid
    with _app.app_context():
        ResourceRequest.query.filter_by(resource_id=rid).delete()
        db.session.commit()
        Resource.query.filter_by(id=rid).delete()
        db.session.commit()
        db.session.remove()


@pytest.fixture(scope="module")
def admin_user(_app):
    """Usuario con role=fiscal_advisor."""
    with _app.app_context():
        u = User(
            email             = "admin_res_test@example.com",
            full_name         = "Admin Recursos Test",
            role              = "fiscal_advisor",
            email_verified_at = datetime.utcnow(),
        )
        u.set_password("admin-pass-res-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
        db.session.remove()
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()
        db.session.remove()


@pytest.fixture
def client(_app):
    return _app.test_client()


@pytest.fixture(autouse=True)
def clear_flask_login_g(_app):
    yield
    from flask import g
    g.pop("_login_user", None)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _login_admin(client):
    r = client.post("/api/login", json={
        "email":    "admin_res_test@example.com",
        "password": "admin-pass-res-1234",
    })
    assert r.status_code == 200, f"Login admin falló: {r.get_json()}"


_VALID_PAYLOAD_TEMPLATE = {
    "name":              "Juan Prueba",
    "email":             "juan.prueba@example.com",
    "exchange":          "bitvavo",
    "bitvavo_status":    "registered_via_link",
    "uid":               "12345678",
    "uid_unknown":       False,
    "telegram_user":     "@juanprueba",
    "legal_accepted":    True,
    "marketing_consent": True,
    # source ya no se envía desde el formulario
}


def _post_solicitud(client, resource_id, overrides=None):
    payload = {**_VALID_PAYLOAD_TEMPLATE, "resource_id": resource_id, **(overrides or {})}
    with patch("app._send_resource_confirmation_email"), \
         patch("app._send_resource_internal_notification"):
        return client.post(
            "/api/recursos/solicitar",
            json=payload,
            content_type="application/json",
        )


# ── Tests de la API pública ────────────────────────────────────────────────────

def test_solicitud_valida_crea_registro(client, resource, _app):
    """POST con datos válidos → 201, registro en BD con status=recibido."""
    r = _post_solicitud(client, resource)
    assert r.status_code == 201, r.get_json()
    data = r.get_json()
    assert data.get("ok") is True
    assert "id" in data

    with _app.app_context():
        db.session.remove()
        rr = ResourceRequest.query.filter_by(id=data["id"]).first()
        assert rr is not None
        assert rr.status             == "recibido"
        assert rr.name               == "Juan Prueba"
        assert rr.email              == "juan.prueba@example.com"
        assert rr.source             is None   # source ya no se recoge
        assert rr.legal_accepted     is True
        assert rr.marketing_consent  is True
        db.session.delete(rr)
        db.session.commit()
        db.session.remove()


def test_solicitud_sin_legal_accepted(client, resource):
    """Sin legal_accepted → 400."""
    r = _post_solicitud(client, resource, {"legal_accepted": False})
    assert r.status_code == 400
    assert "privacidad" in r.get_json().get("error", "").lower()


def test_solicitud_sin_marketing_consent(client, resource):
    """marketing_consent es ahora obligatorio → 400."""
    r = _post_solicitud(client, resource, {"marketing_consent": False})
    assert r.status_code == 400
    assert "comunicaciones" in r.get_json().get("error", "").lower()


def test_solicitud_email_invalido(client, resource):
    """Email sin @ → 400."""
    r = _post_solicitud(client, resource, {"email": "no-es-un-email"})
    assert r.status_code == 400


def test_solicitud_sin_nombre(client, resource):
    """Sin nombre → 400."""
    r = _post_solicitud(client, resource, {"name": ""})
    assert r.status_code == 400


def test_solicitud_resource_inexistente(client):
    """resource_id que no existe → 404."""
    r = _post_solicitud(client, 99999)
    assert r.status_code == 404


def test_solicitud_uid_vacio_sin_uid_unknown_rechazada(client, resource):
    """UID vacío sin uid_unknown → 400 (ahora es obligatorio)."""
    r = _post_solicitud(client, resource, {"uid": None, "uid_unknown": False})
    assert r.status_code == 400
    assert "uid" in r.get_json().get("error", "").lower()


def test_solicitud_uid_vacio_con_uid_unknown_aceptada(client, resource, _app):
    """UID vacío pero uid_unknown=True → 201, entra como recibido."""
    r = _post_solicitud(client, resource, {"uid": None, "uid_unknown": True})
    assert r.status_code == 201
    rr_id = r.get_json()["id"]

    with _app.app_context():
        db.session.remove()
        rr = ResourceRequest.query.filter_by(id=rr_id).first()
        assert rr.status      == "recibido"
        assert rr.uid         is None
        assert rr.uid_unknown is True
        db.session.delete(rr)
        db.session.commit()
        db.session.remove()


def test_solicitud_exchange_invalido(client, resource):
    """Exchange fuera de la lista permitida → 400."""
    r = _post_solicitud(client, resource, {"exchange": "kraken"})
    assert r.status_code == 400


def test_solicitud_exchanges_validos(client, resource, _app):
    """Bitvavo y Binance son los únicos exchanges aceptados."""
    for exch in ("bitvavo", "binance"):
        r = _post_solicitud(client, resource, {
            "exchange": exch,
            "email":    f"{exch}@test.com",
        })
        assert r.status_code == 201, f"Exchange '{exch}' debería aceptarse: {r.get_json()}"
        with _app.app_context():
            db.session.remove()
            rr = ResourceRequest.query.filter_by(email=f"{exch}@test.com").first()
            if rr:
                db.session.delete(rr)
                db.session.commit()
            db.session.remove()


def test_solicitud_exchange_none_aceptado(client, resource, _app):
    """Exchange vacío (None) también se acepta — campo opcional."""
    r = _post_solicitud(client, resource, {"exchange": None, "email": "noexch@test.com"})
    assert r.status_code == 201
    with _app.app_context():
        db.session.remove()
        rr = ResourceRequest.query.filter_by(email="noexch@test.com").first()
        if rr:
            db.session.delete(rr)
            db.session.commit()
        db.session.remove()


def test_source_no_se_guarda(client, resource, _app):
    """El campo source no se recibe ni guarda (eliminado del formulario)."""
    r = _post_solicitud(client, resource, {"email": "nosource@test.com"})
    assert r.status_code == 201
    with _app.app_context():
        db.session.remove()
        rr = ResourceRequest.query.filter_by(email="nosource@test.com").first()
        assert rr.source is None
        db.session.delete(rr)
        db.session.commit()
        db.session.remove()


# ── Tests de admin ─────────────────────────────────────────────────────────────

def test_admin_list_sin_login(client):
    """GET /api/admin/recursos/solicitudes sin sesión → 401."""
    r = client.get("/api/admin/recursos/solicitudes")
    assert r.status_code == 401


def test_admin_list_con_admin(client, resource, admin_user, _app):
    """Admin ve la lista de solicitudes."""
    # Crear una solicitud directamente
    with _app.app_context():
        rr = ResourceRequest(
            resource_id    = resource,
            name           = "Visible Para Admin",
            email          = "admin_visible@example.com",
            legal_accepted = True,
            status         = "recibido",
        )
        db.session.add(rr)
        db.session.commit()
        rr_id = rr.id
        db.session.remove()

    _login_admin(client)
    r = client.get("/api/admin/recursos/solicitudes")
    assert r.status_code == 200
    ids = [item["id"] for item in r.get_json()]
    assert rr_id in ids

    with _app.app_context():
        ResourceRequest.query.filter_by(id=rr_id).delete()
        db.session.commit()
        db.session.remove()


def test_admin_cambiar_estado(client, resource, admin_user, _app):
    """Admin puede cambiar el estado de una solicitud."""
    with _app.app_context():
        rr = ResourceRequest(
            resource_id    = resource,
            name           = "Cambio Estado",
            email          = "cambio_estado@example.com",
            legal_accepted = True,
            status         = "recibido",
        )
        db.session.add(rr)
        db.session.commit()
        rr_id = rr.id
        db.session.remove()

    _login_admin(client)
    r = client.post(
        f"/api/admin/recursos/solicitudes/{rr_id}/estado",
        json={"status": "aprobado"},
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.get_json()["status"] == "aprobado"

    with _app.app_context():
        db.session.remove()
        rr = ResourceRequest.query.filter_by(id=rr_id).first()
        assert rr.status == "aprobado"
        db.session.delete(rr)
        db.session.commit()
        db.session.remove()


def test_admin_estado_invalido(client, resource, admin_user, _app):
    """Estado fuera del enum → 400."""
    with _app.app_context():
        rr = ResourceRequest(
            resource_id    = resource,
            name           = "Estado Inválido",
            email          = "estado_invalido@example.com",
            legal_accepted = True,
            status         = "recibido",
        )
        db.session.add(rr)
        db.session.commit()
        rr_id = rr.id
        db.session.remove()

    _login_admin(client)
    r = client.post(
        f"/api/admin/recursos/solicitudes/{rr_id}/estado",
        json={"status": "pendiente_datos"},
        content_type="application/json",
    )
    assert r.status_code == 400

    with _app.app_context():
        ResourceRequest.query.filter_by(id=rr_id).delete()
        db.session.commit()
        db.session.remove()


def test_admin_anadir_nota(client, resource, admin_user, _app):
    """Admin puede añadir una nota interna."""
    with _app.app_context():
        rr = ResourceRequest(
            resource_id    = resource,
            name           = "Nota Test",
            email          = "nota_test@example.com",
            legal_accepted = True,
            status         = "recibido",
        )
        db.session.add(rr)
        db.session.commit()
        rr_id = rr.id
        db.session.remove()

    _login_admin(client)
    r = client.post(
        f"/api/admin/recursos/solicitudes/{rr_id}/nota",
        json={"nota": "Revisado. UID correcto."},
        content_type="application/json",
    )
    assert r.status_code == 200
    assert "Revisado" in r.get_json()["internal_notes"]

    with _app.app_context():
        db.session.remove()
        rr = ResourceRequest.query.filter_by(id=rr_id).first()
        assert "Revisado" in (rr.internal_notes or "")
        db.session.delete(rr)
        db.session.commit()
        db.session.remove()


def test_admin_nota_vacia(client, resource, admin_user, _app):
    """Nota vacía → 400."""
    with _app.app_context():
        rr = ResourceRequest(
            resource_id    = resource,
            name           = "Nota Vacía",
            email          = "nota_vacia@example.com",
            legal_accepted = True,
            status         = "recibido",
        )
        db.session.add(rr)
        db.session.commit()
        rr_id = rr.id
        db.session.remove()

    _login_admin(client)
    r = client.post(
        f"/api/admin/recursos/solicitudes/{rr_id}/nota",
        json={"nota": "   "},
        content_type="application/json",
    )
    assert r.status_code == 400

    with _app.app_context():
        ResourceRequest.query.filter_by(id=rr_id).delete()
        db.session.commit()
        db.session.remove()


def test_admin_delete_sin_login(client, resource, _app):
    """DELETE sin login → 401."""
    with _app.app_context():
        rr = ResourceRequest(
            resource_id=resource, name="Delete Sin Login",
            email="del_no_login@example.com", legal_accepted=True, status="recibido",
        )
        db.session.add(rr); db.session.commit()
        rr_id = rr.id; db.session.remove()

    r = client.delete(f"/api/admin/recursos/solicitudes/{rr_id}")
    assert r.status_code == 401

    with _app.app_context():
        ResourceRequest.query.filter_by(id=rr_id).delete()
        db.session.commit(); db.session.remove()


def test_admin_delete_con_admin(client, resource, admin_user, _app):
    """Admin puede borrar una solicitud existente."""
    with _app.app_context():
        rr = ResourceRequest(
            resource_id=resource, name="Para Borrar",
            email="del_admin@example.com", legal_accepted=True, status="recibido",
        )
        db.session.add(rr); db.session.commit()
        rr_id = rr.id; db.session.remove()

    _login_admin(client)
    r = client.delete(f"/api/admin/recursos/solicitudes/{rr_id}")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    with _app.app_context():
        db.session.remove()
        assert ResourceRequest.query.filter_by(id=rr_id).first() is None
        db.session.remove()


def test_admin_delete_inexistente(client, admin_user, _app):
    """DELETE de id que no existe → 404."""
    _login_admin(client)
    r = client.delete("/api/admin/recursos/solicitudes/99999")
    assert r.status_code == 404


def test_admin_delete_no_toca_resource(client, resource, admin_user, _app):
    """Borrar una solicitud no elimina el Resource asociado."""
    with _app.app_context():
        rr = ResourceRequest(
            resource_id=resource, name="Borrar Sin Tocar Recurso",
            email="del_safe@example.com", legal_accepted=True, status="recibido",
        )
        db.session.add(rr); db.session.commit()
        rr_id = rr.id; db.session.remove()

    _login_admin(client)
    client.delete(f"/api/admin/recursos/solicitudes/{rr_id}")

    with _app.app_context():
        from models import Resource
        db.session.remove()
        assert Resource.query.filter_by(id=resource).first() is not None
        db.session.remove()


# ── Tests de modelos ───────────────────────────────────────────────────────────

def test_to_dict_basic_y_full(_app, resource):
    """to_dict() basic y full no lanzan excepción y contienen los campos esperados."""
    with _app.app_context():
        rr = ResourceRequest(
            resource_id       = resource,
            name              = "Dict Test",
            email             = "dict_test@example.com",
            exchange          = "bitvavo",
            bitvavo_status    = "registered_via_link",
            uid               = "abc123",
            uid_unknown       = False,
            telegram_user     = "@dicttest",
            source            = "telegram",
            legal_accepted    = True,
            marketing_consent = False,
            status            = "recibido",
        )
        db.session.add(rr)
        db.session.commit()

        d = rr.to_dict()
        assert d["status"]       == "recibido"
        assert d["status_label"] == "Recibido"
        assert d["email"]        == "dict_test@example.com"

        d_full = rr.to_dict(full=True)
        assert d_full["bitvavo_status"]       == "registered_via_link"
        assert d_full["bitvavo_status_label"] == "Se ha registrado con tu enlace"
        assert d_full["source"]               == "telegram"
        assert d_full["marketing_consent"]    is False

        db.session.delete(rr)
        db.session.commit()
        db.session.remove()


# ── Tests de páginas públicas ──────────────────────────────────────────────────

def test_pagina_recursos_publica(client, resource):
    """GET /recursos → 200."""
    r = client.get("/recursos")
    assert r.status_code == 200
    assert b"Recursos" in r.data


def test_pagina_recurso_individual(client, resource):
    """GET /recursos/test-resource → 200 con título del recurso."""
    r = client.get("/recursos/test-resource")
    assert r.status_code == 200
    assert b"Test Resource" in r.data


def test_pagina_recurso_no_existe(client):
    """GET /recursos/slug-que-no-existe → 404."""
    r = client.get("/recursos/slug-que-no-existe")
    assert r.status_code == 404


# ── Tests de plantillas de email ───────────────────────────────────────────────

def test_email_templates_no_fallan(_app, resource):
    """Las plantillas de email de recursos no lanzan excepción."""
    from email_templates import (
        resource_request_confirmation_email,
        resource_request_internal_email,
    )
    with _app.app_context():
        res = Resource.query.filter_by(id=resource).first()
        rr  = ResourceRequest(
            resource_id    = resource,
            name           = "Email Template Test",
            email          = "email_tmpl@example.com",
            exchange       = "bitvavo",
            bitvavo_status = "had_account",
            uid            = None,
            uid_unknown    = True,
            telegram_user  = "@test",
            source         = "youtube",
            legal_accepted = True,
            marketing_consent = True,
            status         = "recibido",
        )
        rr.id = 9999  # simular ID sin persistir

        html1, text1 = resource_request_confirmation_email(rr, res)
        assert html1 and len(html1) > 50
        assert text1 and "Email Template Test" in text1

        html2, text2 = resource_request_internal_email(rr, res, "https://marianosevilla.com")
        assert html2 and len(html2) > 50
        assert text2 and "email_tmpl@example.com" in text2
        assert "No sabe dónde encontrarlo" in text2

        db.session.remove()
