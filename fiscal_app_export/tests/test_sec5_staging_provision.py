"""CI-only static guard for an explicit one-shot staging SQL provisioning."""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sec5_staging_provision import validate_provision_envelope, DBNAME, ROLE
from sec5_staging_isolation import (
    DATABASE_HOST, PROJECT_ID, STAGING_ENV_ID, STAGING_SERVICE_ID,
)


@pytest.fixture
def valid():
    return {
        "RAILWAY_PROJECT_ID": PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": STAGING_ENV_ID,
        "RAILWAY_SERVICE_ID": STAGING_SERVICE_ID,
        "DATABASE_URL": "postgresql+psycopg2://ci-user:ci-password@"
                        + DATABASE_HOST + "/railway",
        "PROCESSING_ERROR_EMAILS_ENABLED": "0",
        "SEC5_STAGING_ISOLATION": "READONLY",
        "SEC5_STAGING_PROVISION": "EXPLICIT_ONCE",
        "SEC5_STAGING_PROVISION_PASSWORD": "a" * 60,
    }


def test_valid_staging_env_only(valid):
    validate_provision_envelope(valid)
    assert DBNAME != "railway"
    assert ROLE != "postgres"


@pytest.mark.parametrize("field", [
    "SEC5_STAGING_PROVISION", "SEC5_STAGING_PROVISION_PASSWORD",
    "RAILWAY_ENVIRONMENT_ID", "RAILWAY_SERVICE_ID", "DATABASE_URL",
])
def test_reject_missing(valid, field):
    del valid[field]
    with pytest.raises(Exception):
        validate_provision_envelope(valid)


def test_wrong_password(valid):
    valid["SEC5_STAGING_PROVISION_PASSWORD"] = "a" * 20
    with pytest.raises(ValueError):
        validate_provision_envelope(valid)


def test_wrong_host(valid):
    valid["DATABASE_URL"] = valid["DATABASE_URL"].replace(
        DATABASE_HOST, "postgres.railway.internal"
    )
    with pytest.raises(Exception):
        validate_provision_envelope(valid)


def test_production_fails_even_with_valid_password(valid):
    valid["RAILWAY_ENVIRONMENT_ID"] = "912b2cae-38a8-4900-a2d0-13f85e749971"
    with pytest.raises(Exception):
        validate_provision_envelope(valid)


def test_staging_provision_never_imported_by_web_startup():
    root = Path(__file__).resolve().parents[1]
    for file in ("app.py", "Procfile", "bootstrap_db.py", "startup_schema_gate.py"):
        assert "sec5_staging_provision" not in (root / file).read_text(encoding="utf-8")
