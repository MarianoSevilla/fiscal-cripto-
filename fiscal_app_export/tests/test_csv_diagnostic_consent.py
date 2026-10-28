"""Consent-gated diagnostic-file transport. Never calls the email provider."""
import base64
import io
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch
from datetime import datetime

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "synthetic-csv-diag-consent-secret")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app as flask_app, db
from models import User


@pytest.fixture
def authenticated_client(monkeypatch):
    config_keys = (
        "TESTING", "RATELIMIT_ENABLED", "WTF_CSRF_ENABLED",
        "SESSION_COOKIE_SECURE", "CSV_DIAGNOSTIC_SUPPORT_ENABLED",
    )
    previous = {k: flask_app.config.get(k) for k in config_keys}
    flask_app.config.update({
        "TESTING": True, "RATELIMIT_ENABLED": False,
        "WTF_CSRF_ENABLED": False, "SESSION_COOKIE_SECURE": False,
        "CSV_DIAGNOSTIC_SUPPORT_ENABLED": True,
    })
    with flask_app.app_context():
        db.create_all()
        user = User(email="diag-consent-fixture@example.invalid", full_name="Diag Test", email_verified_at=datetime.utcnow())
        user.set_password("csv-diagnostic-fixture-password")
        db.session.add(user)
        db.session.commit()
        uid = user.id
        db.session.remove()
    client = flask_app.test_client()
    res = client.post("/api/login", json={
        "email": "diag-consent-fixture@example.invalid",
        "password": "csv-diagnostic-fixture-password",
    })
    assert res.status_code == 200
    monkeypatch.setenv("CSV_DIAGNOSTIC_SUPPORT_EMAIL", "support@example.invalid")
    monkeypatch.setenv("RESEND_API_KEY", "synthetic-resend-key")
    try:
        yield client
    finally:
        with flask_app.app_context():
            db.session.remove()
            db.session.query(User).filter_by(id=uid).delete()
            db.session.commit()
            db.session.remove()
        flask_app.config.update(previous)


def request_data(*, consent=True, filename="user-private-file.csv", content=b"Date,Coin,Amount\\n2025-01-01,BTC,1\\n"):
    fields = {
        "exchange": "binance",
        "archivo": (io.BytesIO(content), filename),
    }
    if consent:
        fields["consentimiento"] = "ACEPTO_ENVIO_DIAGNOSTICO_V1"
    return fields


def send(client, **kw):
    return client.post(
        "/api/diagnostico-archivo", data=request_data(**kw),
        content_type="multipart/form-data", headers={"Origin": "http://localhost"},
    )


def test_no_consent_never_calls_provider(authenticated_client):
    with patch("requests.post") as provider:
        response = send(authenticated_client, consent=False)
    assert response.status_code == 400
    provider.assert_not_called()


def test_feature_off_fails_closed(authenticated_client):
    flask_app.config["CSV_DIAGNOSTIC_SUPPORT_ENABLED"] = False
    with patch("requests.post") as provider:
        response = send(authenticated_client)
    assert response.status_code == 404
    provider.assert_not_called()


def test_unauthenticated_never_calls_provider(authenticated_client):
    anonymous = flask_app.test_client()
    with patch("requests.post") as provider:
        response = send(anonymous)
    assert response.status_code == 401
    provider.assert_not_called()


def test_cross_origin_is_blocked(authenticated_client):
    with patch("requests.post") as provider:
        response = authenticated_client.post(
            "/api/diagnostico-archivo", data=request_data(),
            content_type="multipart/form-data",
            headers={"Origin": "https://attacker.invalid"},
        )
    assert response.status_code == 403
    provider.assert_not_called()


@pytest.mark.parametrize("filename,content,status", [
    ("bad.exe", b"contents", 400),
    ("bad.csv", b"", 413),
    ("bad.csv", b"A\x00B", 400),
    ("bad.xlsx", b"not-a-zip", 400),
    ("bad.xls", b"not-an-xls", 400),
    ("big.csv", b"X" * (8 * 1024 * 1024 + 1), 413),
])
def test_invalid_file_never_sent(authenticated_client, filename, content, status):
    with patch("requests.post") as provider:
        response = send(authenticated_client, filename=filename, content=content)
    assert response.status_code == status
    provider.assert_not_called()


def test_valid_explicit_consent_transfers_one_file_no_original_name(authenticated_client):
    provider_response = MagicMock(status_code=200)
    with patch("requests.post", return_value=provider_response) as provider:
        response = send(authenticated_client, filename="cliente-identificable.csv")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert provider.call_count == 1
    url = provider.call_args.args[0]
    payload = provider.call_args.kwargs["json"]
    assert url == "https://api.resend.com/emails"
    assert payload["to"] == ["support@example.invalid"]
    assert payload["attachments"][0]["filename"] == "diagnostico_binance.csv"
    assert "cliente-identificable" not in str(payload)
    assert base64.b64decode(payload["attachments"][0]["content"]) == b"Date,Coin,Amount\\n2025-01-01,BTC,1\\n"
    assert "ACEPTO_ENVIO_DIAGNOSTICO_V1" in payload["text"]


def test_provider_rejection_returns_failure_without_sensitive_logs(authenticated_client, caplog):
    with patch("requests.post", return_value=MagicMock(status_code=422)):
        response = send(authenticated_client, filename="secret-user-iban.csv")
    assert response.status_code == 502
    assert "secret-user-iban" not in caplog.text


def test_no_filename_in_logs_on_unexpected_network_failure(authenticated_client, caplog):
    import requests
    with patch("requests.post", side_effect=requests.Timeout("PRIVATE-CSV-CONTENT")):
        response = send(authenticated_client, filename="private-portfolio.csv")
    assert response.status_code == 502
    assert "PRIVATE-CSV-CONTENT" not in caplog.text
    assert "private-portfolio" not in caplog.text
