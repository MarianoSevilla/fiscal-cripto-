"""No network / no real database: staging preflight's fail-closed contract."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sec5_staging_isolation import (
    DATABASE_HOST, STAGING_VARIABLES, StagingIsolationError, validate_envelope,
    PROJECT_ID, STAGING_ENV_ID, STAGING_SERVICE_ID,
)


@pytest.fixture
def safe_env():
    return {
        "RAILWAY_PROJECT_ID": PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": STAGING_ENV_ID,
        "RAILWAY_SERVICE_ID": STAGING_SERVICE_ID,
        "DATABASE_URL": (
            "postgresql+psycopg2://user:testing-secret@"
            + DATABASE_HOST + ":5432/railway"
        ),
        "PROCESSING_ERROR_EMAILS_ENABLED": "0",
        "SEC5_STAGING_ISOLATION": "READONLY",
    }


def test_known_staging_envelope_passes_without_connecting(safe_env):
    validate_envelope(safe_env)


@pytest.mark.parametrize("var", [
    "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_SERVICE_ID", "DATABASE_URL",
    "PROCESSING_ERROR_EMAILS_ENABLED", "SEC5_STAGING_ISOLATION",
])
def test_missing_envelope_fails(safe_env, var):
    safe_env.pop(var)
    with pytest.raises(StagingIsolationError):
        validate_envelope(safe_env)


@pytest.mark.parametrize("host", [
    "postgres.railway.internal", "127.0.0.1", "localhost",
    "postgres-zzky.example.com", "postgres-zzky.railway.internal.evil.invalid",
])
def test_rejects_non_staging_host(safe_env, host):
    safe_env["DATABASE_URL"] = safe_env["DATABASE_URL"].replace(DATABASE_HOST, host)
    with pytest.raises(StagingIsolationError):
        validate_envelope(safe_env)


@pytest.mark.parametrize("key", STAGING_VARIABLES)
def test_rejects_every_external_provider_key(safe_env, key):
    safe_env[key] = "nonempty-test-value"
    with pytest.raises(StagingIsolationError):
        validate_envelope(safe_env)


def test_rejects_sqlite_fallback(safe_env):
    safe_env["DATABASE_URL"] = "sqlite:///local.db"
    with pytest.raises(StagingIsolationError):
        validate_envelope(safe_env)


def test_rejects_prod_environment_even_if_host_matches(safe_env):
    safe_env["RAILWAY_ENVIRONMENT_ID"] = "912b2cae-38a8-4900-a2d0-13f85e749971"
    with pytest.raises(StagingIsolationError):
        validate_envelope(safe_env)


def test_no_ddl_or_credential_printing_in_script():
    path = Path(__file__).resolve().parents[1] / "sec5_staging_isolation.py"
    source = path.read_text(encoding="utf-8")
    assert "SET TRANSACTION READ ONLY" in source
    assert "tx.rollback()" in source
    for forbidden in ("CREATE ROLE", "CREATE TABLE", "DROP TABLE",
                      "db.create_all(", "db.session.commit(", "os.system("):
        assert forbidden not in source
    assert "details redacted" in source
