"""No network / no real database: staging preflight's fail-closed contract."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sec5_staging_isolation import (
    DATABASE_HOST, STAGING_VARIABLES, StagingIsolationError, validate_envelope,
    PROJECT_ID, STAGING_ENV_ID, STAGING_SERVICE_ID,
    RUNTIME_DATABASE, RUNTIME_LOGIN, validate_runtime_acl,
)


@pytest.fixture
def safe_env():
    return {
        "RAILWAY_PROJECT_ID": PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": STAGING_ENV_ID,
        "RAILWAY_SERVICE_ID": STAGING_SERVICE_ID,
        "DATABASE_URL": (
            "postgresql+psycopg2://" + RUNTIME_LOGIN + ":testing-secret@"
            + DATABASE_HOST + ":5432/" + RUNTIME_DATABASE
        ),
        "PROCESSING_ERROR_EMAILS_ENABLED": "0",
        "SEC5_STAGING_ISOLATION": "READONLY",
        "SEC5_STAGING_DB_MODE": "RUNTIME",
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


@pytest.mark.parametrize("mutate", [
    lambda x: x.update({"SEC5_STAGING_DB_MODE": "BOOTSTRAP"}),
    lambda x: x.update({"SEC5_STAGING_PROVISION": "EXPLICIT_ONCE"}),
    lambda x: x.update({"SEC5_STAGING_PROVISION_PASSWORD": "unnecessary-secret"}),
    lambda x: x.update({"DATABASE_URL": x["DATABASE_URL"].replace(
        RUNTIME_LOGIN + ":", "postgres:")}),
    lambda x: x.update({"DATABASE_URL": x["DATABASE_URL"].replace(
        RUNTIME_DATABASE, "railway")}),
    lambda x: x.update({"DATABASE_URL": x["DATABASE_URL"].replace(
        ":5432/", ":5433/")}),
])
def test_unsafe_runtime_identity_fails(safe_env, mutate):
    mutate(safe_env)
    with pytest.raises(StagingIsolationError):
        validate_envelope(safe_env)


def role_row():
    return (
        RUNTIME_DATABASE, RUNTIME_LOGIN, RUNTIME_LOGIN,
        True, False, False, False, False, False, False, False,
        False, False, False,
    )


def grant_rows():
    return [(f"orm_{i}", True, True, True, True) for i in range(17)] + [
        ("alembic_version", True, False, False, False)
    ]


def test_valid_runtime_pg18_catalog_contract():
    validate_runtime_acl(role_row(), grant_rows(),
                         {f"orm_{i}" for i in range(17)})


@pytest.mark.parametrize("index", list(range(3, 14)))
def test_any_privilege_elevation_fails(index):
    r = list(role_row())
    r[index] = not r[index]
    with pytest.raises(StagingIsolationError):
        validate_runtime_acl(tuple(r), grant_rows(),
                             {f"orm_{i}" for i in range(17)})


@pytest.mark.parametrize("case", ["superuser", "database", "alembic", "missing",
                                   "extra", "missing_grant", "duplicate"])
def test_catalog_grant_invariants_fail(case):
    r = list(role_row())
    grants = grant_rows()
    tables = {f"orm_{i}" for i in range(17)}
    if case == "superuser":
        r[4] = True
    elif case == "database":
        r[0] = "railway"
    elif case == "alembic":
        grants[-1] = ("alembic_version", True, True, False, False)
    elif case == "missing":
        grants = grants[:-1]
    elif case == "extra":
        grants.append(("foreign_table", True, False, False, False))
    elif case == "missing_grant":
        grants[0] = ("orm_0", True, False, True, True)
    elif case == "duplicate":
        grants.append(grants[0])
    with pytest.raises(StagingIsolationError):
        validate_runtime_acl(tuple(r), grants, tables)
