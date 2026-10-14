"""Exercise final S01 schema writer against fresh disposable PG18 on CI ONLY.

The CI fixture redirects its injected transport to 127.0.0.1 and replaces
the pinned Railway cluster fingerprint with a disposable system_identifier.
None of these CI-only helpers is copied into the Railway runtime image.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Executed as tests/qa_*.py: expose the fiscal_app_export package root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2

import schema_preflight as pg
import schema_bootstrap_one_shot as live
import schema_postcheck_readonly as parked
from private_maintenance_preflight import PreflightDenied, check_pristine_readonly
from private_maintenance_rehearsal import CI_DSN
from qa_s01_b11a_restored_bootstrap_pg18 import (
    FORBIDDEN_REAL_CLUSTERS, assert_disposable_clusters,
    create_empty_ci_database, require_fixture_scope,
)


def fake_runtime():
    return {
        "RAILWAY_PROJECT_ID": pg.PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": pg.ENVIRONMENT_ID,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": pg.SERVICE_ID,
        "RAILWAY_PRIVATE_DOMAIN": pg.SERVICE_PRIVATE_DOMAIN,
        "TARGET_DATABASE_URL":
            "postgresql://postgres:fake-ci-only-secret@"
            "postgres-im3h.railway.internal:5432/railway",
        live.APPROVAL_KEY: live.APPROVAL_INTENT,
    }


def local_connection(fake_dsn, **kwargs):
    # Controlled test seam: *never* use the user-provided fake host.
    assert fake_dsn == fake_runtime()["TARGET_DATABASE_URL"]
    return psycopg2.connect(
        CI_DSN, connect_timeout=kwargs["connect_timeout"],
        sslmode="prefer", options=kwargs["options"],
    )


def local_postcheck_connection(dsn, **kwargs):
    # GitHub Actions PG18 container is non-TLS. This substitute exists ONLY
    # in CI and cannot be selected by the deployed one-shot entrypoint.
    if dsn != CI_DSN or kwargs.get("sslmode") != "require":
        raise RuntimeError("CI_POSTCHECK_SCOPE")
    return psycopg2.connect(
        CI_DSN, connect_timeout=kwargs["connect_timeout"],
        sslmode="prefer", options=kwargs["options"],
    )


def local_pristine_probe(_):
    conn = psycopg2.connect(
        CI_DSN, connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=10000",
    )
    try:
        check_pristine_readonly(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT (pg_catalog.pg_control_system()).system_identifier::text"
            )
            cluster = str(cur.fetchone()[0])
        conn.rollback()
        return cluster
    finally:
        conn.close()


def run():
    require_fixture_scope(dict(os.environ))
    if os.environ.get("S01_SCHEMA_BOOTSTRAP_APPROVAL"):
        raise RuntimeError("LIVE_APPROVAL_PRESENT_IN_CI")
    create_empty_ci_database(5432)

    conn = psycopg2.connect(CI_DSN, connect_timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_setting('server_version_num'), "
                "(pg_catalog.pg_control_system()).system_identifier::text"
            )
            version, cluster = cur.fetchone()
            version, cluster = str(version), str(cluster)
        conn.rollback()
    finally:
        conn.close()
    if not version.startswith("18") or cluster in FORBIDDEN_REAL_CLUSTERS:
        raise RuntimeError("NOT_DISPOSABLE_PG18")
    assert_disposable_clusters(cluster, "7777777777777777777")

    with patch.object(pg, "TARGET_CLUSTER", cluster), patch.object(
        pg, "TARGET_PG_VERSION", version
    ):
        # The actual production controller + actual ORM/Alembic/postcheck run.
        status = live.bootstrap_once(
            fake_runtime(), preflight_fn=local_pristine_probe,
            connect_fn=local_connection,
            migrate_fn=lambda _: live._real_schema_changes(CI_DSN),
            postcheck_fn=lambda _: live._read_only_postcheck(
                CI_DSN, connect_fn=local_postcheck_connection
            ),
        )
        if status != live.PASS:
            raise RuntimeError("FAILED_FULL_SCHEMA_BOOTSTRAP")

        # Validate the ACTUAL SQL of the independent readonly parking image
        # against the populated CI schema. B11B's pristine check is no longer
        # appropriate once Alembic and the application tables exist.
        post_conn = psycopg2.connect(
            CI_DSN, connect_timeout=5,
            options="-c default_transaction_read_only=on",
        )
        try:
            with post_conn.cursor() as cur:
                cur.execute(parked.SQL)
                values = cur.fetchone()
            post_conn.rollback()
            if parked.validate_output(
                "|".join(str(value) for value in values) + "\n"
            ) != cluster:
                raise RuntimeError("READONLY_PARKING_QUERY_INVALID")
        finally:
            post_conn.close()
        print("S01 FINAL CI READONLY POSTCHECK PASS: verified live CI schema and Alembic head")

        try:
            live.bootstrap_once(
                fake_runtime(), preflight_fn=local_pristine_probe,
                connect_fn=local_connection,
                migrate_fn=lambda _: live._real_schema_changes(CI_DSN),
                postcheck_fn=lambda _: live._read_only_postcheck(
                CI_DSN, connect_fn=local_postcheck_connection
            ),
            )
        except PreflightDenied as exc:
            if exc.code != "NOT_PRISTINE":
                raise RuntimeError("INCORRECT_REPLAY_REFUSAL") from None
        else:
            raise RuntimeError("BOOTSTRAP_REPLAY_SUCCEEDED")

    print(
        "S01 FINAL CI PASS: actual one-shot controller and full ORM/Alembic "
        "to z9a0b1c2d3e4 on disposable PG18; advisory lock, "
        "postcheck and replay denial; zero Railway access", flush=True
    )


if __name__ == "__main__":
    run()
