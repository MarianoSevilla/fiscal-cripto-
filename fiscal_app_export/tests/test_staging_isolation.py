"""No network, Flask, Railway, real payments or database needed for STG-LOCK-001."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from staging_isolation import (
    STAGING_BASE_URL, STAGING_DB_HOST, STAGING_ENVIRONMENT_ID,
    STAGING_HOST, STAGING_PROJECT_ID, STAGING_SERVICE_ID,
    DISABLED_STAGING_CREDENTIALS, install_staging_email_barrier,
    is_staging_candidate, staging_request_denial, validate_staging_isolation,
)


def staging_env():
    return {
        "FLASK_ENV": "staging",
        "RAILWAY_ENVIRONMENT_NAME": "staging",
        "RAILWAY_ENVIRONMENT_ID": STAGING_ENVIRONMENT_ID,
        "RAILWAY_SERVICE_ID": STAGING_SERVICE_ID,
        "RAILWAY_PROJECT_ID": STAGING_PROJECT_ID,
        "APP_BASE_URL": STAGING_BASE_URL,
        "DATABASE_URL": f"postgresql+psycopg2://user:secret@{STAGING_DB_HOST}:5432/railway",
        "PAYPAL_ENVIRONMENT": "sandbox",
        "SECRET_KEY": "nondefault-synthetic-secret",
    }


def test_valid_staging_configuration_has_no_side_effects():
    env = staging_env()
    assert validate_staging_isolation(env) is True
    assert env == staging_env()


def test_unrelated_production_or_local_config_is_unchanged():
    assert validate_staging_isolation({"FLASK_ENV": "production", "RAILWAY_ENVIRONMENT_NAME": "production"}) is False
    assert validate_staging_isolation({"FLASK_ENV": "testing"}) is False
    assert is_staging_candidate(staging_env()) is True


@pytest.mark.parametrize("variable", [
    "FLASK_ENV", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID", "APP_BASE_URL", "PAYPAL_ENVIRONMENT",
])
def test_wrong_identity_refuses_startup(variable):
    env = staging_env()
    env[variable] = "production"
    with pytest.raises(RuntimeError, match=variable):
        validate_staging_isolation(env)


def test_railway_staging_cannot_claim_production_mode():
    env = staging_env()
    env["FLASK_ENV"] = "production"
    assert is_staging_candidate(env)
    with pytest.raises(RuntimeError, match="FLASK_ENV"):
        validate_staging_isolation(env)


@pytest.mark.parametrize("url", [
    "", "sqlite:///test.db", "postgresql://user:secret@postgres-zzky.railway.internal:5432/railway",
    "postgresql+psycopg2://user:secret@postgres.railway.internal:5432/railway",
    "postgresql+psycopg2://user:secret@postgres-zzky.railway.internal:5433/railway",
    "postgresql+psycopg2://user:secret@postgres-zzky.railway.internal:5432/production",
    "postgresql+psycopg2://user@postgres-zzky.railway.internal:5432/railway",
    "postgresql+psycopg2://user:secret@postgres-zzky.railway.internal:5432/railway?host=evil",
    "postgresql+psycopg2://user:secret@postgres-zzky.railway.internal:invalid/railway",
])
def test_bad_database_connection_fails_closed(url):
    env = staging_env()
    env["DATABASE_URL"] = url
    with pytest.raises(RuntimeError, match="DATABASE_URL") as info:
        validate_staging_isolation(env)
    assert "secret" not in str(info.value)


@pytest.mark.parametrize("variable", DISABLED_STAGING_CREDENTIALS)
def test_all_external_credentials_blocked_even_sandbox(variable):
    env = staging_env()
    env[variable] = "synthetic-credential-not-usable"
    with pytest.raises(RuntimeError, match=variable) as info:
        validate_staging_isolation(env)
    assert "synthetic-credential-not-usable" not in str(info.value)


@pytest.mark.parametrize("path,method", [
    ("/api/pago/iniciar/fake", "POST"), ("/api/pago/paypal/capture", "GET"),
    ("/api/webhooks/paypal", "POST"), ("/api/webhooks/stripe", "POST"),
    ("/pagar/fake", "GET"), ("/static/pagar.html", "GET"),
    ("/api/admin/asesoramiento/solicitudes/2", "GET"),
    ("/api/asesoramiento/files/download/3", "GET"),
    ("/auth/google/callback", "GET"),
    ("/api/admin/comunicaciones/campaigns/1", "GET"),
    ("/api/descargar/fake.pdf", "GET"),
    ("/api/asesoramiento/precios", "GET"),
    ("/admin/asesoramiento", "GET"),
    ("/api/asesoramiento/solicitar", "POST"), ("/api/contacto", "POST"),
    ("/api/admin/comunicaciones/drafts/1/send", "POST"),
    ("/api/admin/asesoramiento/solicitudes/1", "DELETE"),
    ("/signup", "POST"), ("/api/721", "POST"),
])
def test_staging_rejects_sensitive_and_all_mutation_paths(path, method):
    result = staging_request_denial(host=STAGING_HOST, path=path, method=method)
    assert result is not None
    assert result[0] == 503


@pytest.mark.parametrize("path", [
    "/", "/healthz", "/como-funciona", "/contacto", "/faq",
    "/exchanges/bitvavo", "/metodo-fifo-criptomonedas",
    "/asesoramiento-fiscal-criptomonedas", "/robots.txt",
])
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_only_reviewed_public_pages_are_reachable(path, method):
    assert staging_request_denial(host=STAGING_HOST, path=path, method=method) is None


@pytest.mark.parametrize("path", [
    "/static/css/landing.css", "/static/js/app.js", "/static/js/app.mjs",
    "/static/img/logo.svg", "/static/img/logo.png", "/static/img/photo.webp",
    "/static/img/photo.avif", "/static/fonts/body.woff2", "/static/favicon.ico",
])
def test_safe_public_assets_are_reachable(path):
    assert staging_request_denial(host=STAGING_HOST, path=path, method="GET") is None


@pytest.mark.parametrize("path", [
    "/verify-email", "/verify-email-result", "/reset-password/signed-token",
    "/dashboard", "/account", "/fiscal", "/modelo721",
    "/login/", "/signup/", "/recursos", "/recursos/experimento-bitcoin",
    "/stats", "/stats-v2", "/pedir-asesoramiento",
    "/mis-solicitudes-fiscales", "/auth/google/callback",
    "/api/me", "/api/pago/paypal/capture", "/api/webhooks/paypal",
    "/api/webhooks/stripe", "/api", "/admin", "/pagar/test-token",
    "/static/pagar.html", "/static/signup.html", "/static/login.html",
    "/static/landing.html", "/static/report.pdf", "/static/report.csv",
    "/static/config.json", "/static/config.xml",
    "/static/../verify.js", "/static/dir//main.js",
    "/brand-new-unaudited-get", "/como-funciona/",
])
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_all_unreviewed_read_paths_fail_closed(path, method):
    result = staging_request_denial(host=STAGING_HOST, path=path, method=method)
    assert result is not None
    assert result[0] == 503


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("path", ["/", "/healthz", "/como-funciona", "/static/css/landing.css"])
def test_mutation_methods_are_blocked_even_on_allowlisted_paths(path, method):
    assert staging_request_denial(host=STAGING_HOST, path=path, method=method)[0] == 503


def test_email_verification_get_that_commits_to_db_is_not_public():
    # Regression: app.py /verify-email is GET but writes user.email_verified_at.
    assert staging_request_denial(host=STAGING_HOST, path="/verify-email", method="GET")[0] == 503


def test_cross_host_and_cross_origin_rejected():
    assert staging_request_denial(host="marianosevilla.com", path="/", method="GET")[0] == 421
    assert staging_request_denial(host=STAGING_HOST, origin="https://www.marianosevilla.com", path="/", method="GET")[0] == 403
    assert staging_request_denial(host=STAGING_HOST, origin=STAGING_BASE_URL, path="/", method="GET") is None


def test_resend_api_is_blocked_in_background_code_too():
    mock_resend = SimpleNamespace(Emails=SimpleNamespace(send=lambda **kw: "unexpected"))
    install_staging_email_barrier(mock_resend)
    with pytest.raises(RuntimeError, match="outbound email disabled"):
        mock_resend.Emails.send(to=["example@example.test"])
