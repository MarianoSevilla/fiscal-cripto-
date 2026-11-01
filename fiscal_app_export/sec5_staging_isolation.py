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
    if parsed.get_backend_name() != "postgresql" or parsed.host != DATABASE_HOST:
        raise StagingIsolationError("database host not the isolated staging Postgres")
    if any(environ.get(key, "") for key in STAGING_VARIABLES):
        raise StagingIsolationError("external provider credentials still enabled")
    if environ.get("PROCESSING_ERROR_EMAILS_ENABLED") != "0":
        raise StagingIsolationError("processing error emails not explicitly disabled")
    if environ.get("SEC5_STAGING_ISOLATION") != "READONLY":
        raise StagingIsolationError("explicit isolation opt-in absent")


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
                row = connection.exec_driver_sql(
                    "SELECT current_user = session_user, "
                    "current_setting('is_superuser')"
                ).one()
                if read_only != "on" or not 180000 <= version < 190000:
                    raise StagingIsolationError("not PostgreSQL 18 read-only")
                # Do not claim role separation while old admin DATABASE_URL is used.
                print(
                    "SEC5 STAGING ISOLATION: PASS "
                    "(PostgreSQL18, read-only, staging-only hostname, "
                    "providers disabled, superuser=" + row[1] + ")",
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
