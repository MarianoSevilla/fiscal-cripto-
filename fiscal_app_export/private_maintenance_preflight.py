"""STG-B10A: private, READ-ONLY PostgreSQL maintenance preflight.

No schema writes, Alembic, app import, web listeners, or provider calls.
A real maintenance service ID has NOT been approved: the CLI MUST fail closed.
Future execution of bootstrap_db.py requires a new, separately reviewed change
and explicit authorization; this module intentionally has no DDL entrypoint.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
import os
import sys
from urllib.parse import urlsplit

from staging_isolation import DISABLED_STAGING_CREDENTIALS


@dataclass(frozen=True)
class MaintenanceIdentity:
    project_id: str
    environment_id: str
    service_id: str | None
    service_domain: str
    db_hostname: str


# Fixed IDs independently read from the isolated Railway laboratory.
# None is a deliberately CLOSED gate: B10B must pin the *real* executor ID
# after a separate Railway authorization and renewed operational inventory.
PINNED_IDENTITY = MaintenanceIdentity(
    project_id="5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e",
    environment_id="3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8",
    service_id=None,
    service_domain="s01-lab-maintenance.railway.internal",
    db_hostname="postgres.railway.internal",
)

FORBIDDEN_CREDENTIALS = frozenset(DISABLED_STAGING_CREDENTIALS) | {
    "STRIPE_PUBLISHABLE_KEY",
    "TURNSTILE_SECRET_KEY",
    "TURNSTILE_SITE_KEY",
    "RESEND_API_KEY",
    "SENTRY_DSN",
}
FORBIDDEN_NETWORK_SETTINGS = (
    "RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL", "APP_BASE_URL", "PORT",
)
DISABLED_FEATURES = (
    "ENABLE_ADVISORY_STATUS_EMAILS",
    "ENABLE_ADVISORY_UPLOADS",
    "PROCESSING_ERROR_EMAILS_ENABLED",
)


class PreflightDenied(RuntimeError):
    """Only safe, fixed classification codes are exposed to callers."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PreflightReport:
    database: str
    postgres_version: int
    public_relations: int
    public_functions: int
    public_types: int
    other_user_schemas: int
    extra_extensions: int
    event_triggers: int


def validate_identity(
    env: Mapping[str, str], *, identity: MaintenanceIdentity = PINNED_IDENTITY
) -> None:
    """Pure validation, without any I/O; tests supply synthetic identities."""
    if not identity.service_id:
        raise PreflightDenied("SERVICE_UNPINNED")

    required = {
        "RAILWAY_PROJECT_ID": identity.project_id,
        "RAILWAY_ENVIRONMENT_ID": identity.environment_id,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": identity.service_id,
        "RAILWAY_PRIVATE_DOMAIN": identity.service_domain,
        "FLASK_ENV": "staging",
    }
    if any(env.get(name) != expected for name, expected in required.items()):
        raise PreflightDenied("RAILWAY_IDENTITY")

    if any((env.get(name) or "").strip() for name in FORBIDDEN_NETWORK_SETTINGS):
        raise PreflightDenied("PUBLIC_NETWORK")
    if any((env.get(name) or "").strip() for name in FORBIDDEN_CREDENTIALS):
        raise PreflightDenied("EXTERNAL_CREDENTIALS")
    if any(
        (env.get(name) or "").strip().lower() not in ("", "false", "0", "no", "off")
        for name in DISABLED_FEATURES
    ):
        raise PreflightDenied("ACTIVE_FEATURE")
    if (env.get("PAYPAL_ENVIRONMENT") or "").strip().lower() not in ("", "sandbox"):
        raise PreflightDenied("PAYMENT_ENVIRONMENT")

    raw_dsn = env.get("DATABASE_URL") or ""
    try:
        url = urlsplit(raw_dsn)
        safe = (
            url.scheme in ("postgresql", "postgresql+psycopg2")
            and url.hostname == identity.db_hostname
            and url.port == 5432
            and url.path == "/railway"
            and bool(url.username)
            and bool(url.password)
            and not url.query
            and not url.fragment
        )
    except (ValueError, TypeError):
        safe = False
    if not safe:
        raise PreflightDenied("DATABASE_TARGET")


# Fixed SQL only: no interpolated identifiers and no DDL or data reads.
_SQL = (
    "SELECT current_database(), current_setting('server_version_num'), "
    "current_setting('transaction_read_only')",
    "SELECT count(*) FROM pg_catalog.pg_namespace WHERE nspname = 'public'",
    "SELECT count(*) FROM pg_catalog.pg_class AS c "
    "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public'",
    "SELECT count(*) FROM pg_catalog.pg_proc AS p "
    "JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace "
    "WHERE n.nspname = 'public'",
    "SELECT count(*) FROM pg_catalog.pg_type AS t "
    "JOIN pg_catalog.pg_namespace AS n ON n.oid = t.typnamespace "
    "WHERE n.nspname = 'public'",
    "SELECT count(*) FROM pg_catalog.pg_namespace "
    "WHERE nspname <> 'public' AND nspname <> 'information_schema' "
    "AND nspname NOT LIKE 'pg_%'",
    "SELECT count(*) FROM pg_catalog.pg_extension WHERE extname <> 'plpgsql'",
    "SELECT count(*) FROM pg_catalog.pg_event_trigger",
)


def check_pristine_readonly(connection: object) -> PreflightReport:
    """Perform catalog-only checks, in a transaction explicitly READ ONLY."""
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(_SQL[0])
            row = cursor.fetchone()
            if not row or len(row) != 3:
                raise PreflightDenied("DATABASE_IDENTITY")
            database, version, readonly = row
            try:
                version_num = int(version)
            except (ValueError, TypeError):
                raise PreflightDenied("DATABASE_IDENTITY") from None
            if database != "railway" or version_num // 10000 != 18:
                raise PreflightDenied("DATABASE_IDENTITY")
            if readonly != "on":
                raise PreflightDenied("TRANSACTION_NOT_READONLY")

            values = []
            for statement in _SQL[1:]:
                cursor.execute(statement)
                entry = cursor.fetchone()
                if entry is None or len(entry) != 1:
                    raise PreflightDenied("CATALOG_CHECK")
                count = entry[0]
                if type(count) is not int or count < 0:
                    raise PreflightDenied("CATALOG_CHECK")
                values.append(count)

            schema_present, *counts = values
            if schema_present != 1 or any(counts):
                raise PreflightDenied("NOT_PRISTINE")
            return PreflightReport(database, version_num, *counts)
    finally:
        # Even successful inspections must never commit.
        connection.rollback()


def run_preflight(
    env: Mapping[str, str],
    connect: Callable[..., object],
    *,
    identity: MaintenanceIdentity = PINNED_IDENTITY,
) -> PreflightReport:
    """Validate FIRST; connect only to the explicitly validated private DSN."""
    validate_identity(env, identity=identity)
    dsn = env["DATABASE_URL"]
    if dsn.startswith("postgresql+psycopg2://"):
        dsn = "postgresql://" + dsn[len("postgresql+psycopg2://"):]
    connection = connect(
        dsn,
        connect_timeout=5,
        sslmode="require",
        application_name="s01-stg-b10a-readonly-preflight",
        options="-c default_transaction_read_only=on -c statement_timeout=5000",
    )
    try:
        return check_pristine_readonly(connection)
    finally:
        connection.close()


def main() -> None:
    # Must reject an unpinned Railway maintenance service BEFORE driver import,
    # DNS lookup or opening a socket. No env variable may unlock this gate.
    try:
        validate_identity(os.environ)
        from psycopg2 import connect
        report = run_preflight(os.environ, connect)
    except PreflightDenied as exc:
        print(f"S01 STG-B10A: NO-GO ({exc.code})", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        # Never print a DBAPI/SQLAlchemy error: it can expose the full DSN.
        print("S01 STG-B10A: NO-GO (INTERNAL; details protected)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print(
        "S01 STG-B10A: PASS (private PostgreSQL "
        f"{report.postgres_version}, empty catalog, transaction READ ONLY)",
        flush=True,
    )


if __name__ == "__main__":
    main()
