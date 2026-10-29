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
