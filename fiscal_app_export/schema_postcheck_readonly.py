"""S01 completed-schema READ-ONLY attestation; safe post-bootstrap parking image.

This is separate from the DDL executable. Only psql SELECT statements are
included, and the image excludes ORM/Alembic/migrations/payment providers.
"""
from __future__ import annotations

import os
import subprocess
import sys

import schema_preflight as target

HEAD = "z9a0b1c2d3e4"
SQL = """
SELECT current_database(), current_setting('server_version_num'),
current_setting('transaction_read_only'),
(pg_catalog.pg_control_system()).system_identifier::text,
(SELECT count(*) FROM pg_catalog.pg_tables
 WHERE schemaname='public' AND tablename IN
 ('alembic_version','users','resources',
  's01_stripe_checkout_attempts','s01_stripe_event_receipts',
  's01_stripe_notification_outbox')),
(SELECT count(*) FROM public.alembic_version),
(SELECT min(version_num) FROM public.alembic_version),
(SELECT count(*) FROM public.resources WHERE slug='experimento-bitcoin'),
(SELECT count(*) FROM pg_catalog.pg_constraint
 WHERE connamespace='public'::regnamespace AND conname IN
 ('ck_s01_attempt_amount','ck_s01_attempt_currency',
  'ck_s01_checkout_status','ck_s01_outbox_kind',
  'ck_s01_outbox_status','uq_s01_attempt_advisory',
  'uq_s01_outbox_attempt_kind')),
(SELECT count(*) FROM pg_catalog.pg_indexes
 WHERE schemaname='public' AND indexname IN
 ('ix_s01_attempt_status','ix_s01_outbox_status'));
"""


class PostcheckDenied(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_output(stdout: str) -> str:
    lines = stdout.strip().splitlines()
    if len(lines) != 1:
        raise PostcheckDenied("RESULT_SHAPE")
    cols = lines[0].split("|")
    if len(cols) != 10 or cols[:3] != ["railway", target.TARGET_PG_VERSION, "on"]:
        raise PostcheckDenied("DATABASE_VERSION_OR_READONLY")
    if cols[3] != target.TARGET_CLUSTER:
        raise PostcheckDenied("WRONG_RECOVERED_CLUSTER")
    if cols[4:] != ["6", "1", HEAD, "1", "7", "2"]:
        raise PostcheckDenied("EXPECTED_SCHEMA_OR_MIGRATIONS_MISSING")
    return cols[3]


def probe_completed_schema(env: dict[str, str], *, runner=subprocess.run) -> str:
    checked_env = target.checked_pg_environment(env)
    try:
        result = runner(
            ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", SQL],
            env=checked_env, capture_output=True, text=True,
            check=False, timeout=25,
        )
    except (OSError, subprocess.SubprocessError):
        raise PostcheckDenied("READONLY_SQL_FAILED") from None
    if result.returncode:
        raise PostcheckDenied("READONLY_SQL_FAILED")
    return validate_output(result.stdout)


def main() -> None:
    try:
        cluster = probe_completed_schema(dict(os.environ))
    except target.SchemaPreflightDenied as exc:
        print("S01 POSTBOOTSTRAP READONLY: NO-GO (" + exc.code + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except PostcheckDenied as exc:
        print("S01 POSTBOOTSTRAP READONLY: NO-GO (" + exc.code + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        print("S01 POSTBOOTSTRAP READONLY: NO-GO (REDACTED_ERROR)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print("S01 POSTBOOTSTRAP READONLY: PASS (Postgres-Im3h " + cluster
          + "; Alembic z9a0b1c2d3e4; table and resource integrity verified)",
          flush=True)


if __name__ == "__main__":
    main()
