"""STG-B11B: dedicated, one-shot READ-ONLY identity preflight for S01 schema target.

Only checks the independent RECOVERY PG18 database, NOT original Postgres.
This container includes no Flask, SQLAlchemy, Alembic, or DDL executor.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

PROJECT_ID = "5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e"
ENVIRONMENT_ID = "3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8"
SERVICE_ID = "007db029-c99d-4a68-a965-fd0de3496614"
SERVICE_PRIVATE_DOMAIN = "s01-lab-schema-preflight.railway.internal"
TARGET_HOST = "postgres-im3h.railway.internal"
TARGET_CLUSTER = "7696517018472497211"
FORBIDDEN_ORIGINAL_CLUSTER = "7696213098351943739"
TARGET_PG_VERSION = "180006"
PUBLIC_MARKERS = (
    "RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL", "APP_BASE_URL",
)
FORBIDDEN_SECRETS = (
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "PAYPAL_CLIENT_SECRET",
    "RESEND_API_KEY", "GOOGLE_CLIENT_SECRET", "SECRET_KEY",
    "SENTRY_DSN", "DATABASE_URL", "SOURCE_DATABASE_URL",
    "PGHOST", "PGPASSWORD", "PGSERVICE", "PGPASSFILE",
)
SQL = """
SELECT current_database(), current_setting('server_version_num'),
current_setting('transaction_read_only'),
(pg_catalog.pg_control_system()).system_identifier::text,
(SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n
 ON n.oid=c.relnamespace WHERE n.nspname='public'),
(SELECT count(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n
 ON n.oid=p.pronamespace WHERE n.nspname='public'),
(SELECT count(*) FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n
 ON n.oid=t.typnamespace WHERE n.nspname='public'),
(SELECT count(*) FROM pg_catalog.pg_namespace
 WHERE nspname NOT IN ('public','information_schema','pg_catalog')
 AND nspname NOT LIKE 'pg_toast%' AND nspname NOT LIKE 'pg_temp_%'),
(SELECT count(*) FROM pg_catalog.pg_extension WHERE extname <> 'plpgsql'),
(SELECT count(*) FROM pg_catalog.pg_event_trigger);
"""


class SchemaPreflightDenied(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def checked_pg_environment(env: dict[str, str]) -> dict[str, str]:
    expected = (
        ("RAILWAY_PROJECT_ID", PROJECT_ID),
        ("RAILWAY_ENVIRONMENT_ID", ENVIRONMENT_ID),
        ("RAILWAY_ENVIRONMENT_NAME", "lab"),
        ("RAILWAY_SERVICE_ID", SERVICE_ID),
        ("RAILWAY_PRIVATE_DOMAIN", SERVICE_PRIVATE_DOMAIN),
    )
    if any(env.get(k) != v for k, v in expected):
        raise SchemaPreflightDenied("RAILWAY_IDENTITY")
    if any((env.get(k) or "").strip() for k in PUBLIC_MARKERS):
        raise SchemaPreflightDenied("PUBLIC_NETWORK")
    if any((env.get(k) or "").strip() for k in FORBIDDEN_SECRETS):
        raise SchemaPreflightDenied("UNAPPROVED_SECRETS")
    try:
        u = urlsplit(env.get("TARGET_DATABASE_URL", ""))
        valid = (
            u.scheme == "postgresql" and u.hostname == TARGET_HOST
            and u.port == 5432 and u.path == "/railway"
            and not u.query and not u.fragment
            and bool(u.username) and bool(u.password)
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise SchemaPreflightDenied("WRONG_TARGET")
    return {
        "PGHOST": TARGET_HOST, "PGPORT": "5432", "PGDATABASE": "railway",
        "PGUSER": unquote(u.username),
        "PGPASSWORD": unquote(u.password),
        "PGSSLMODE": "require",
        "PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=10000",
        "PATH": env.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",
    }


def checked_readonly_catalog(stdout: str) -> str:
    lines = stdout.strip().splitlines()
    if len(lines) != 1:
        raise SchemaPreflightDenied("RESULT_SHAPE")
    columns = lines[0].split("|")
    if len(columns) != 10 or columns[:3] != ["railway", TARGET_PG_VERSION, "on"]:
        raise SchemaPreflightDenied("DATABASE_OR_VERSION")
    cluster = columns[3]
    if not re.fullmatch(r"[0-9]{16,20}", cluster):
        raise SchemaPreflightDenied("CLUSTER_ID_INVALID")
    if cluster == FORBIDDEN_ORIGINAL_CLUSTER:
        raise SchemaPreflightDenied("ORIGINAL_CLUSTER_FORBIDDEN")
    if cluster != TARGET_CLUSTER:
        raise SchemaPreflightDenied("UNEXPECTED_RECOVERY_CLUSTER")
    if columns[4:] != ["0"] * 6:
        raise SchemaPreflightDenied("SCHEMA_NOT_PRISTINE")
    return cluster


def preflight(env, runner=subprocess.run):
    child_env = checked_pg_environment(env)
    try:
        result = runner(
            ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", SQL],
            env=child_env, text=True, capture_output=True,
            check=False, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        raise SchemaPreflightDenied("READONLY_QUERY_FAILED") from None
    if result.returncode:
        raise SchemaPreflightDenied("READONLY_QUERY_FAILED")
    return checked_readonly_catalog(result.stdout)


def main():
    try:
        cluster = preflight(dict(os.environ))
    except SchemaPreflightDenied as exc:
        print("S01 STG-B11B: NO-GO (" + exc.code + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        print("S01 STG-B11B: NO-GO (REDACTED_ERROR)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print(
        "S01 STG-B11B: PASS (READ ONLY; schema target PG18.6 "
        "cluster=" + cluster + "; pristine)",
        flush=True,
    )


if __name__ == "__main__":
    main()
