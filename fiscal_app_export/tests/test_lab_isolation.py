"""STG-B04 synthetic, offline, no DB/provider/network test of the lab identity."""
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab_isolation import (
    LAB_IDENTITY, LAB_FORBIDDEN_CREDENTIALS, LAB_DISABLED_FEATURE_FLAGS,
    RAILWAY_HEALTHCHECK_HOST, LabIdentity, is_lab_candidate,
    validate_lab_isolation, lab_request_denial, install_lab_email_barrier,
)
from staging_isolation import (
    validate_staging_isolation, STAGING_PROJECT_ID, STAGING_ENVIRONMENT_ID,
    STAGING_SERVICE_ID, STAGING_BASE_URL, STAGING_DB_HOST,
)

CI_PINS = replace(
    LAB_IDENTITY,
    web_service_id="ci-only-fictional-web-service",
    base_url="https://s01-lab-ci.invalid",
)


def lab_env():
    return {
        "FLASK_ENV": "staging",
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_PROJECT_ID": CI_PINS.project_id,
        "RAILWAY_ENVIRONMENT_ID": CI_PINS.environment_id,
        "RAILWAY_SERVICE_ID": CI_PINS.web_service_id,
        "APP_BASE_URL": CI_PINS.base_url,
        "PAYPAL_ENVIRONMENT": "sandbox",
        "DATABASE_URL": (
            f"postgresql+psycopg2://fictional:inert-ci-only"
            f"@{CI_PINS.db_hostname}:5432/railway"
        ),
        "SECRET_KEY": "ci-only-fake-session-secret",
    }


def staging_env():
    return {
        "FLASK_ENV": "staging",
        "RAILWAY_ENVIRONMENT_NAME": "staging",
        "RAILWAY_PROJECT_ID": STAGING_PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": STAGING_ENVIRONMENT_ID,
        "RAILWAY_SERVICE_ID": STAGING_SERVICE_ID,
        "APP_BASE_URL": STAGING_BASE_URL,
        "PAYPAL_ENVIRONMENT": "sandbox",
        "DATABASE_URL": f"postgresql+psycopg2://ci:secret@{STAGING_DB_HOST}:5432/railway",
    }


def test_actual_lab_runtime_intentionally_refuses_without_web_pins():
    with pytest.raises(RuntimeError, match="not pinned"):
        validate_lab_isolation(lab_env())


def test_synthetic_identity_allows_validation_without_io():
    assert validate_lab_isolation(lab_env(), identity=CI_PINS)
    assert lab_env() == lab_env()


def test_staging_keeps_its_exact_original_firewall():
    assert is_lab_candidate(staging_env()) is False
    assert validate_lab_isolation(staging_env()) is False
    assert validate_staging_isolation(staging_env()) is True


def test_unrelated_production_and_local_inert():
    for env in (
        {"FLASK_ENV": "production", "RAILWAY_ENVIRONMENT_NAME": "production"},
        {"FLASK_ENV": "testing"},
        {},
    ):
        assert is_lab_candidate(env) is False
        assert validate_lab_isolation(env) is False


@pytest.mark.parametrize("variable", [
    "FLASK_ENV", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_SERVICE_ID", "RAILWAY_ENVIRONMENT_NAME", "APP_BASE_URL",
    "PAYPAL_ENVIRONMENT",
])
def test_any_wrong_lab_identity_fails_closed(variable):
    env = lab_env()
    env[variable] = "production"
    with pytest.raises(RuntimeError, match=variable):
        validate_lab_isolation(env, identity=CI_PINS)


@pytest.mark.parametrize("key", [
    "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_SERVICE_ID",
])
def test_any_single_lab_marker_cannot_downgrade_to_production(key):
    env = {"FLASK_ENV": "production", key: lab_env()[key]}
    assert is_lab_candidate(env, identity=CI_PINS)
    with pytest.raises(RuntimeError):
        validate_lab_isolation(env, identity=CI_PINS)


@pytest.mark.parametrize("url", [
    "", "sqlite:///ci.sqlite",
    "postgresql://ci:pw@postgres.railway.internal:5432/railway",
    "postgresql+psycopg2://ci:pw@postgres-zzky.railway.internal:5432/railway",
    "postgresql+psycopg2://ci:pw@postgres.railway.internal:5432/prod",
    "postgresql+psycopg2://ci:pw@postgres.railway.internal:5433/railway",
    "postgresql+psycopg2://ci@postgres.railway.internal:5432/railway",
    "postgresql+psycopg2://ci:pw@postgres.railway.internal:5432/railway?host=prod",
    "postgresql+psycopg2://ci:pw@postgres.railway.internal:bogus/railway",
    "postgresql+psycopg2://ci:pw@postgres.railway.internal:5432/railway#evil",
])
def test_lab_database_cross_wiring_never_allowed(url):
    env = lab_env()
    env["DATABASE_URL"] = url
    with pytest.raises(RuntimeError, match="DATABASE_URL") as error:
        validate_lab_isolation(env, identity=CI_PINS)
    assert "inert-ci-only" not in str(error.value)


@pytest.mark.parametrize("key", LAB_FORBIDDEN_CREDENTIALS)
def test_no_external_credentials_even_in_sandbox(key):
    env = lab_env()
    env[key] = "fictional-secret-never-log"
    with pytest.raises(RuntimeError, match=key) as error:
        validate_lab_isolation(env, identity=CI_PINS)
    assert "fictional-secret-never-log" not in str(error.value)


@pytest.mark.parametrize("key", LAB_DISABLED_FEATURE_FLAGS)
def test_email_or_upload_feature_must_be_disabled(key):
    env = lab_env()
    env[key] = "true"
    with pytest.raises(RuntimeError, match=key):
        validate_lab_isolation(env, identity=CI_PINS)
    env[key] = "false"
    assert validate_lab_isolation(env, identity=CI_PINS) is True


@pytest.mark.parametrize("key,value", [
    ("FLASK_ENV","testing"), ("FLASK_ENV","development"),
    ("RAILWAY_ENVIRONMENT_NAME","staging"),
    ("RAILWAY_ENVIRONMENT_ID",STAGING_ENVIRONMENT_ID),
    ("RAILWAY_PROJECT_ID",STAGING_PROJECT_ID),
    ("RAILWAY_SERVICE_ID",STAGING_SERVICE_ID),
    ("APP_BASE_URL",STAGING_BASE_URL),
])
def test_original_staging_identifiers_cannot_be_used_as_lab(key, value):
    env = lab_env()
    env[key] = value
    with pytest.raises(RuntimeError):
        validate_lab_isolation(env, identity=CI_PINS)


@pytest.mark.parametrize("path,method", [
    ("/", "GET"), ("/dashboard", "GET"), ("/signup/", "POST"),
    ("/verify-email", "GET"), ("/api/me", "GET"),
    ("/api/asesoramiento/solicitar", "POST"),
    ("/api/admin/asesoramiento/solicitudes", "GET"),
    ("/api/webhooks/stripe", "POST"), ("/api/webhooks/paypal", "POST"),
    ("/api/pago/paypal/capture", "GET"), ("/api/pago/iniciar/x", "POST"),
    ("/static/test.js", "GET"), ("/healthz", "POST"), ("/healthz", "OPTIONS"),
])
def test_only_healthcheck_accessible(path, method):
    assert lab_request_denial(
        host="s01-lab-ci.invalid", path=path, method=method, identity=CI_PINS
    )[0] == 503


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_lab_healthcheck_on_canonical_host_only(method):
    assert lab_request_denial(
        host="s01-lab-ci.invalid", path="/healthz", method=method, identity=CI_PINS
    ) is None
    assert lab_request_denial(
        host=RAILWAY_HEALTHCHECK_HOST, path="/healthz", method=method, identity=CI_PINS
    ) is None


@pytest.mark.parametrize("path,method,origin", [
    ("/", "GET", None),
    ("/healthz", "POST", None),
    ("/healthz", "GET", "https://s01-lab-ci.invalid"),
    ("/api/webhooks/stripe", "POST", None),
])
def test_healthcheck_host_cannot_open_any_other_access(path, method, origin):
    assert lab_request_denial(
        host=RAILWAY_HEALTHCHECK_HOST, path=path, method=method,
        origin=origin, identity=CI_PINS,
    )[0] == 421


@pytest.mark.parametrize("host", [
    "marianosevilla.com", "fiscal-cripto-staging-staging.up.railway.app",
    "postgres.railway.internal", "s01-lab-ci.invalid.evil.test",
    "healthcheck.railway.app:443",
])
def test_bad_hosts_rejected(host):
    assert lab_request_denial(
        host=host, path="/healthz", method="GET", identity=CI_PINS
    )[0] == 421


def test_cross_origin_blocked():
    assert lab_request_denial(
        host="s01-lab-ci.invalid", path="/healthz", method="GET",
        origin="https://www.marianosevilla.com", identity=CI_PINS,
    )[0] == 403


def test_unauthorized_deployment_inertia_even_for_healthcheck():
    assert lab_request_denial(host="healthcheck.railway.app", path="/healthz", method="GET")[0] == 503


def test_resend_barrier_prevents_background_email():
    mock = SimpleNamespace(Emails=SimpleNamespace(send=lambda **kw: "unexpected"))
    install_lab_email_barrier(mock)
    with pytest.raises(RuntimeError, match="outbound email disabled"):
        mock.Emails.send(to=["test@example.invalid"])
