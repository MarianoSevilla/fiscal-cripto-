"""SEC5-PRIV staging isolation preflight — READ ONLY, fail-closed.

Called as the Railway staging *pre-deploy* command before starting Flask.
No schema migration, role modification, secrets, or customer records.
The exact service/environment/database host are hard-coded so that accidentally
pointing staging at production stops the deploy before application startup.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy.engine import make_url

STAGING_ENV_ID = "b2937140-78f7-4347-a9bc-c96333e03b9b"
STAGING_SERVICE_ID = "3eecda71-9f53-4b33-a308-887d835b7fce"
PROJECT_ID = "e04f04a8-3aae-4aed-9073-638601f8ca30"
DATABASE_HOST = "postgres-zzky.railway.internal"
RUNTIME_DATABASE = "sec5_priv_stage_20261101"
RUNTIME_LOGIN = "sec5_runtime_stage"
STAGING_VARIABLES = (
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
    "RESEND_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID",
    "TURNSTILE_SECRET_KEY", "FISCAL_ADVISOR_EMAILS",
    "FISCAL_ADVISORY_NOTIFY_EMAILS",
)


class StagingIsolationError(Exception):
    pass


def validate_envelope(environ: dict[str, str]) -> None:
    required = {
        "RAILWAY_PROJECT_ID": PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": STAGING_ENV_ID,
        "RAILWAY_SERVICE_ID": STAGING_SERVICE_ID,
    }
    if any(environ.get(key) != value for key, value in required.items()):
        raise StagingIsolationError("wrong Railway service/project/environment")
    uri = environ.get("DATABASE_URL", "")
    if not uri:
        raise StagingIsolationError("missing DATABASE_URL")
    try:
        parsed = make_url(uri)
    except Exception as exc:
        raise StagingIsolationError("invalid DATABASE_URL") from None
    if (
        parsed.get_backend_name() != "postgresql"
        or parsed.drivername != "postgresql+psycopg2"
        or parsed.host != DATABASE_HOST
        or parsed.port != 5432
        or parsed.database != RUNTIME_DATABASE
        or parsed.username != RUNTIME_LOGIN
        or not parsed.password
        or parsed.query
        or environ.get("SEC5_STAGING_DB_MODE") != "RUNTIME"
        or environ.get("SEC5_STAGING_PROVISION")
        or environ.get("SEC5_STAGING_PROVISION_PASSWORD")
    ):
        raise StagingIsolationError("database is not the limited staging runtime")
    if any(environ.get(key, "") for key in STAGING_VARIABLES):
        raise StagingIsolationError("external provider credentials still enabled")
    if environ.get("PROCESSING_ERROR_EMAILS_ENABLED") != "0":
        raise StagingIsolationError("processing error emails not explicitly disabled")
    if environ.get("SEC5_STAGING_ISOLATION") != "READONLY":
        raise StagingIsolationError("explicit isolation opt-in absent")


def validate_runtime_acl(role_row: tuple, grants: list[tuple], model_tables: set[str]) -> None:
    """Validate only PostgreSQL catalog observations: never read/write customer data."""
    expected_role = (
        RUNTIME_DATABASE, RUNTIME_LOGIN, RUNTIME_LOGIN,
        True, False, False, False, False, False, False, False,
        False, False, False,
    )
    # database, current_user, session_user; login; superuser/bypassrls/
    # createrole/createdb/replication/inherit; schema/database CREATE;
    # any role membership
    if tuple(role_row) != expected_role:
        raise StagingIsolationError("runtime role not least-privileged")
    if len(model_tables) != 17:
        raise StagingIsolationError("ORM table inventory changed")
    records = {t: (s, i, u, d) for t, s, i, u, d in grants}
    if len(records) != len(grants):
        raise StagingIsolationError("duplicate database table metadata")
    if set(records) != model_tables | {"alembic_version"}:
        raise StagingIsolationError("unexpected table DML rights")
    for name in model_tables:
        if records[name] != (True, True, True, True):
            raise StagingIsolationError("required ORM table grants missing")
    if records["alembic_version"] != (True, False, False, False):
        raise StagingIsolationError("Alembic must remain SELECT-only")


def verify_readonly() -> None:
    validate_envelope(dict(os.environ))
    # Import the real application ONLY after the precise DB host and env gate.
    from app import app, db

    with app.app_context():
        with db.engine.connect() as connection:
            tx = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                read_only = connection.exec_driver_sql(
                    "SHOW transaction_read_only"
                ).scalar_one()
                version = int(connection.exec_driver_sql(
                    "SHOW server_version_num"
                ).scalar_one())
                if read_only != "on" or not 180000 <= version < 190000:
                    raise StagingIsolationError("not PostgreSQL 18 read-only")
                role_row = connection.exec_driver_sql("""
                    SELECT current_database(), current_user, session_user,
                           r.rolcanlogin, r.rolsuper, r.rolbypassrls,
                           r.rolcreaterole, r.rolcreatedb, r.rolreplication,
                           r.rolinherit,
                           has_schema_privilege(current_user, 'public', 'CREATE'),
                           has_database_privilege(
                               current_user, current_database(), 'CREATE'),
                           EXISTS (
                               SELECT 1 FROM pg_auth_members m
                               WHERE m.member = r.oid
                           )
                    FROM pg_roles r WHERE r.rolname = current_user
                """).one()
                grant_rows = connection.exec_driver_sql("""
                    SELECT c.relname,
                           has_table_privilege(current_user,c.oid,'SELECT'),
                           has_table_privilege(current_user,c.oid,'INSERT'),
                           has_table_privilege(current_user,c.oid,'UPDATE'),
                           has_table_privilege(current_user,c.oid,'DELETE')
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname='public' AND c.relkind IN ('r','p')
                """).all()
                validate_runtime_acl(
                    role_row, grant_rows, set(db.metadata.tables)
                )
                print(
                    "SEC5 STAGING ISOLATION: PASS "
                    "(PostgreSQL18, read-only, staging-only hostname, "
                    "providers disabled, limited_role=verified, 17 ORM ACL)",
                    flush=True,
                )
            finally:
                tx.rollback()


def main() -> None:
    try:
        verify_readonly()
    except Exception:
        # Never log a SQLAlchemy traceback, DSN, user email or secret.
        print("SEC5 STAGING ISOLATION: NO-GO (details redacted)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
