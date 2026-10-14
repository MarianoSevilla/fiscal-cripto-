"""S01 closeout — reviewed, approval-gated, ONE-SHOT lab schema bootstrap.

NOT deployed. This program NEVER connects until a *separate exact approval*
is explicitly provisioned to s01-lab-schema-preflight in Railway. Do NOT set
the approval variable or switch its image without owner authorization.

ONLY target Postgres-Im3h / railway / PG18.6 / cluster 7696517018472497211.
This entrypoint never imports the web app, listens on a port, retries,
drops objects, manipulates the original PostgreSQL or performs payments.
A failure can leave partial DDL: NO automatic compensation or retry.
"""
from __future__ import annotations

import os
import sys

import schema_preflight as target

APPROVAL_KEY = "S01_SCHEMA_BOOTSTRAP_APPROVAL"
APPROVAL_INTENT = (
    "ONE-SCHEMA-BOOTSTRAP:POSTGRES-IM3H:"
    "7696517018472497211:z9a0b1c2d3e4"
)
HEAD = "z9a0b1c2d3e4"
BASELINE = "m6n7o8p9q0r1"
LOCK_KEYS = (2026, 1010)
PASS = "S01_SCHEMA_BOOTSTRAPPED_POSTGRES_IM3H"


class BootstrapDenied(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_release(env: dict[str, str]) -> str:
    """Fail BEFORE socket/driver import on wrong approval or wrong service."""
    if env.get(APPROVAL_KEY) != APPROVAL_INTENT:
        raise BootstrapDenied("EXACT_OWNER_APPROVAL_ABSENT")
    try:
        opts = target.checked_pg_environment(env)
    except target.SchemaPreflightDenied as exc:
        raise BootstrapDenied("WRONG_LAB_" + exc.code) from None
    if env.get("S01_RECOVERY_WRITE_APPROVAL"):
        raise BootstrapDenied("RESTORE_APPROVAL_CROSS_CONTAMINATION")
    if opts.get("PGHOST") != target.TARGET_HOST:
        raise BootstrapDenied("TARGET_HOST_MISMATCH")
    # No DB access for the original Postgres service or any other host/DB.
    return env["TARGET_DATABASE_URL"]


def _assert_correct_cluster(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_database(), current_setting('server_version_num'), "
            "(pg_catalog.pg_control_system()).system_identifier::text"
        )
        row = cur.fetchone()
    if row != ("railway", target.TARGET_PG_VERSION, target.TARGET_CLUSTER):
        raise BootstrapDenied("WRITER_CLUSTER_IDENTITY_MISMATCH")


def _real_schema_changes(dsn: str):
    """Reuses the exact B10C CI-proven metadata and Alembic procedure."""
    from flask_migrate import stamp, upgrade
    import private_maintenance_rehearsal as rehearsal

    rehearsal.assert_graph_head()
    if rehearsal.EXPECTED_HEAD != HEAD or rehearsal.FRESH_BASELINE != BASELINE:
        raise BootstrapDenied("MIGRATION_GRAPH_MISMATCH")
    app, db = rehearsal._minimal_flask_context(dsn)
    with app.app_context():
        db.create_all()
        stamp(directory=str(rehearsal.MIGRATION_DIRECTORY), revision=BASELINE)
        upgrade(directory=str(rehearsal.MIGRATION_DIRECTORY), revision=HEAD)


def _read_only_postcheck(dsn: str):
    import psycopg2
    import private_maintenance_rehearsal as rehearsal

    conn = psycopg2.connect(
        dsn, connect_timeout=5, sslmode="require",
        options="-c default_transaction_read_only=on -c statement_timeout=15000",
    )
    try:
        conn.set_session(readonly=True)
        _assert_correct_cluster(conn)
        conn.rollback()
        rehearsal._check_post_bootstrap(conn)
    finally:
        conn.close()


def bootstrap_once(
    env: dict[str, str], *,
    preflight_fn=None,
    connect_fn=None,
    migrate_fn=None,
    postcheck_fn=None,
) -> str:
    """No automatic retry. Tests inject synthetic substitutes only.

    In production main() supplies no injected hooks.
    The advisory lock prevents *cooperative* bootstrap overlap, but it does
    not make multi-step DDL atomic nor protect against an outside writer.
    """
    dsn = validate_release(env)

    import psycopg2
    import private_maintenance_rehearsal as rehearsal

    if preflight_fn is None:
        preflight_fn = target.preflight
    if connect_fn is None:
        connect_fn = psycopg2.connect
    if migrate_fn is None:
        migrate_fn = _real_schema_changes
    if postcheck_fn is None:
        postcheck_fn = _read_only_postcheck

    # The read-only B11B probe is executed again just before any DB write.
    if preflight_fn(env) != target.TARGET_CLUSTER:
        raise BootstrapDenied("SCHEMA_PREFLIGHT_MISMATCH")
    rehearsal.assert_graph_head()

    lock_conn = connect_fn(
        dsn, connect_timeout=5, sslmode="require",
        options="-c statement_timeout=15000",
    )
    acquired = False
    try:
        lock_conn.autocommit = True
        _assert_correct_cluster(lock_conn)
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s,%s)", LOCK_KEYS)
            acquired = bool(cur.fetchone()[0])
        if not acquired:
            raise BootstrapDenied("CONCURRENT_BOOTSTRAP")
        # Recheck after acquiring the lock; any objects => DENY.
        if preflight_fn(env) != target.TARGET_CLUSTER:
            raise BootstrapDenied("SCHEMA_CHANGED_BEFORE_DDL")
        # The first real write of this program may happen inside migrate_fn.
        migrate_fn(dsn)
        postcheck_fn(dsn)
        return PASS
    finally:
        if acquired:
            try:
                with lock_conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s,%s)", LOCK_KEYS)
            finally:
                lock_conn.close()
        else:
            lock_conn.close()


def main() -> None:
    try:
        result = bootstrap_once(dict(os.environ))
        if result != PASS:
            raise BootstrapDenied("INVALID_POSTCHECK_RESULT")
    except BootstrapDenied as exc:
        print("S01 SCHEMA BOOTSTRAP: NO-GO (" + exc.code + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except target.SchemaPreflightDenied as exc:
        print("S01 SCHEMA BOOTSTRAP: NO-GO (PRECHECK_" + exc.code + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        # Avoid leaking credentials, SQL data, DB urls or stack traces.
        print("S01 SCHEMA BOOTSTRAP: NO-GO (REDACTED_ERROR; "
              "POSSIBLE_PARTIAL_SCHEMA; NO_AUTOMATIC_RETRY)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print("S01 SCHEMA BOOTSTRAP: PASS (one approved schema init; "
          "Postgres-Im3h cluster=" + target.TARGET_CLUSTER
          + "; Alembic head=" + HEAD + "; postcheck complete)", flush=True)


if __name__ == "__main__":
    main()
