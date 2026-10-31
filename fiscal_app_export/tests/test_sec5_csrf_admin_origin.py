"""Cross-origin regression for admin mutating endpoints (synthetic HTTP only).

The test does not authenticate or mutate real resources. It checks that
the request boundary rejects an explicit hostile Origin before a view runs.
"""
import os
import sys
import tempfile

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-csrf-boundary")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.config["RATELIMIT_ENABLED"] = False
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    return flask_app.test_client()


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/admin/recursos/solicitudes/1/estado"),
    ("POST", "/api/admin/recursos/solicitudes/1/nota"),
    ("DELETE", "/api/admin/recursos/solicitudes/1"),
    ("PATCH", "/api/admin/contactos/1"),
])
def test_cross_origin_admin_mutation_rejected_before_auth(client, method, path):
    response = client.open(
        path, method=method,
        headers={"Origin": "https://outside.example", "Sec-Fetch-Site": "cross-site"},
        json={"status": "approved", "accion": "archivar", "nota": "test"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "Origen de solicitud no válido."


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/admin/recursos/solicitudes/1/estado"),
    ("PATCH", "/api/admin/contactos/1"),
])
def test_hostile_origin_rejected_even_without_fetch_metadata(client, method, path):
    response = client.open(
        path, method=method,
        headers={"Origin": "https://evil.example"},
        json={"status": "approved", "accion": "archivar"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "Origen de solicitud no válido."


def test_cross_site_fetch_metadata_rejected_without_origin(client):
    response = client.patch(
        "/api/admin/contactos/1",
        headers={"Sec-Fetch-Site": "cross-site"},
        json={"accion": "archivar"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "Origen de solicitud no válido."


def test_same_origin_is_not_blocked_by_new_boundary(client):
    response = client.patch(
        "/api/admin/contactos/1",
        headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"},
        json={"accion": "archivar"},
    )
    assert response.get_json(silent=True) != {"error": "Origen de solicitud no válido."}
    # Authorization (not CSRF) must still prevent an anonymous write.
    assert response.status_code in (401, 302, 403)


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/admin/recursos/solicitudes/1/estado"),
    ("PATCH", "/api/admin/contactos/1"),
])
def test_same_site_other_subdomain_is_rejected(client, method, path):
    """SameSite cookie policy does not stop a different same-site origin."""
    response = client.open(
        path, method=method,
        headers={"Origin": "https://other.marianosevilla.com", "Sec-Fetch-Site": "same-site"},
        json={"status": "approved", "accion": "archivar"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "Origen de solicitud no válido."


def test_missing_origin_and_fetch_metadata_rejected(client):
    response = client.patch("/api/admin/contactos/1", json={"accion": "archivar"})
    assert response.status_code == 403
    assert response.get_json()["error"] == "Origen de solicitud no válido."


def test_fetch_metadata_same_origin_allows_request_to_reach_authorization(client):
    response = client.patch(
        "/api/admin/contactos/1",
        headers={"Sec-Fetch-Site": "same-origin"},
        json={"accion": "archivar"},
    )
    assert response.get_json(silent=True) != {"error": "Origen de solicitud no válido."}
    assert response.status_code in (401, 302, 403)


def test_same_site_metadata_rejected_without_origin(client):
    response = client.patch(
        "/api/admin/contactos/1",
        headers={"Sec-Fetch-Site": "same-site"},
        json={"accion": "archivar"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "Origen de solicitud no válido."


@pytest.fixture
def authenticated_admin():
    """Synthetic administrator with a dedicated test client and isolated ORM rows."""
    from datetime import datetime
    from flask import g
    from app import db
    from models import User
    flask_app.config["TESTING"] = True
    flask_app.config["RATELIMIT_ENABLED"] = False
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    with flask_app.app_context():
        db.create_all()
        u = User(
            email="csrf_admin_synthetic@example.invalid",
            full_name="CSRF Admin",
            role="admin",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("csrf-fixture-only-123")
        db.session.add(u)
        db.session.commit()
        uid = u.id
        db.session.remove()
    client = flask_app.test_client()
    response = client.post(
        "/api/login",
        json={"email": "csrf_admin_synthetic@example.invalid", "password": "csrf-fixture-only-123"},
    )
    assert response.status_code == 200
    try:
        yield client
    finally:
        with flask_app.app_context():
            db.session.remove()
            g.pop("_login_user", None)
            User.query.filter_by(id=uid).delete()
            db.session.commit()
            db.session.remove()


@pytest.mark.parametrize("headers", [
    {},
    {"Origin": "https://outside.example"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://other.marianosevilla.com", "Sec-Fetch-Site": "same-site"},
])
def test_authenticated_admin_cannot_mutate_without_trusted_origin(authenticated_admin, headers):
    response = authenticated_admin.patch(
        "/api/admin/contactos/999999",
        headers=headers,
        json={"accion": "archivar"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "Origen de solicitud no válido."


def test_authenticated_admin_trusted_origin_reaches_handler(authenticated_admin):
    response = authenticated_admin.patch(
        "/api/admin/contactos/999999",
        headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"},
        json={"accion": "archivar"},
    )
    # Synthetic ID is absent: 404 demonstrates the CSRF barrier allowed
    # the authorized call without modifying a real contact.
    assert response.status_code == 404


# SEC5-CSRF-001 — Communications is an authenticated browser API, not a
# provider webhook. In particular, send-test is a bodyless POST: an attacker
# on a sibling same-site origin could invoke it with a normal HTML form.
_COMMS_WRITES = [
    ("POST", "/api/admin/comunicaciones/drafts"),
    ("PATCH", "/api/admin/comunicaciones/drafts/999999"),
    ("POST", "/api/admin/comunicaciones/drafts/999999/send-test"),
    ("POST", "/api/admin/comunicaciones/drafts/999999/send"),
    ("DELETE", "/api/admin/comunicaciones/campaigns/999999"),
]


@pytest.mark.parametrize("method,path", _COMMS_WRITES)
@pytest.mark.parametrize("headers", [
    {},
    {"Origin": "https://external.example", "Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://fiscal.marianosevilla.com", "Sec-Fetch-Site": "same-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Origin": "http://localhost", "Sec-Fetch-Site": "cross-site"},
])
def test_authenticated_admin_comms_writes_fail_closed_on_untrusted_origin(
        authenticated_admin, method, path, headers):
    response = authenticated_admin.open(
        path, method=method, headers=headers,
        # A plain form is a browser-simple request: must not send even a test.
        data="" if path.endswith("/send-test") else None,
        content_type="text/plain" if path.endswith("/send-test") else None,
    )
    assert response.status_code == 403, (method, path, response.status_code)
    assert response.get_json() == {"error": "Origen de solicitud no válido."}


@pytest.mark.parametrize("headers", [
    {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"},
    {"Sec-Fetch-Site": "same-origin"},
])
def test_authenticated_admin_comms_trusted_origin_reaches_handler(
        authenticated_admin, headers):
    response = authenticated_admin.post(
        "/api/admin/comunicaciones/drafts/999999/send-test",
        headers=headers, data="", content_type="text/plain",
    )
    # The synthetic ID does not exist: 404 proves no false-positive rejection.
    assert response.status_code == 404


def test_admin_comms_send_test_never_calls_mail_service_from_same_site_sibling(
        authenticated_admin, monkeypatch):
    from app import db
    from models import CommunicationCampaign
    from communications import routes as comms_routes

    with flask_app.app_context():
        draft = CommunicationCampaign(
            subject="Synthetic CSRF test", body="Nothing is sent externally",
            recipient_segment="all", status="draft",
        )
        db.session.add(draft)
        db.session.commit()
        draft_id = draft.id
        db.session.remove()

    calls = []

    def fake_send_test(campaign, address):
        calls.append((campaign.id, address))
        return {"ok": True}

    monkeypatch.setattr(comms_routes, "send_test_email", fake_send_test)
    try:
        forged = authenticated_admin.post(
            f"/api/admin/comunicaciones/drafts/{draft_id}/send-test",
            headers={
                "Origin": "https://fiscal.marianosevilla.com",
                "Sec-Fetch-Site": "same-site",
            },
            data="", content_type="text/plain",
        )
        assert forged.status_code == 403
        assert calls == []

        legitimate = authenticated_admin.post(
            f"/api/admin/comunicaciones/drafts/{draft_id}/send-test",
            headers={
                "Origin": "http://localhost",
                "Sec-Fetch-Site": "same-origin",
            },
            data="", content_type="text/plain",
        )
        assert legitimate.status_code == 200, legitimate.get_data(as_text=True)
        assert calls == [(draft_id, "csrf_admin_synthetic@example.invalid")]
    finally:
        with flask_app.app_context():
            db.session.remove()
            db.session.query(CommunicationCampaign).filter_by(id=draft_id).delete()
            db.session.commit()
            db.session.remove()
