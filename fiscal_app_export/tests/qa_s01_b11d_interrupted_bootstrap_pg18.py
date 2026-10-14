"""STG-B11D — test interrupted S01 bootstrap on disposable PG18 only.

Every GitHub Actions matrix job gets its OWN fresh PostgreSQL18 container.
No DROP DATABASE, rollback repair, stage promotion or real Railway access.
The same B10C rehearse_once() writes to a fixed local CI database, then
a deliberately injected failure leaves it dirty for second-run rejection.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2

import private_maintenance_rehearsal as rehearsal
from private_maintenance_preflight import PreflightDenied
from qa_s01_b11a_restored_bootstrap_pg18 import (
    assert_disposable_clusters,
    create_empty_ci_database,
    pristine_cluster,
    require_fixture_scope,
)

ALLOWED_CASES = frozenset((
    "after-models",
    "after-stamp",
    "mid-upgrade",
    "after-upgrade",
))


class SyntheticInterruption(RuntimeError):
    """Induced fault, never an authorization for recovery."""


class InterruptedRunDenied(RuntimeError):
    """Any departure from safe expected behavior means FAIL CI."""


def snapshot() -> tuple:
    """Capture only catalog schema metadata and synthetic seed counts."""
    conn = psycopg2.connect(
        rehearsal.CI_DSN, connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=10000",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT relname, relkind FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' ORDER BY relname,relkind"
            )
            relations = tuple(cur.fetchall())
            cur.execute(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE connamespace='public'::regnamespace ORDER BY conname"
            )
            constraints = tuple(x[0] for x in cur.fetchall())
            cur.execute(
                "SELECT to_regclass('public.alembic_version') IS NOT NULL, "
                "to_regclass('public.users') IS NOT NULL"
            )
            version_present, users_present = cur.fetchone()
            version_values = ()
            if version_present:
                cur.execute("SELECT version_num FROM public.alembic_version ORDER BY 1")
                version_values = tuple(row[0] for row in cur.fetchall())
            cur.execute(
                "SELECT to_regclass('public.resources') IS NOT NULL"
            )
            resources_present = bool(cur.fetchone()[0])
            resources_count = None
            if resources_present:
                cur.execute("SELECT count(*) FROM public.resources")
                resources_count = cur.fetchone()[0]
        conn.rollback()
        return (
            relations, constraints, bool(version_present),
            bool(users_present), version_values, resources_count,
        )
    finally:
        conn.close()


def verify_lock_is_released():
    # Advisory locks must not survive a crash or aborted migration attempt.
    conn = psycopg2.connect(rehearsal.CI_DSN, connect_timeout=5)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s,%s)", rehearsal.LOCK_KEYS)
            if not cur.fetchone()[0]:
                raise InterruptedRunDenied("STUCK_ADVISORY_LOCK")
            cur.execute("SELECT pg_advisory_unlock(%s,%s)", rehearsal.LOCK_KEYS)
            if not cur.fetchone()[0]:
                raise InterruptedRunDenied("LOCK_RELEASE_FAILED")
    finally:
        conn.close()


def interrupt_case(env, case):
    if case == "after-models":
        # db.create_all() completed and persisted. Interrupt *before* stamp.
        with patch("flask_migrate.stamp",
                   side_effect=SyntheticInterruption("AFTER_MODELS")):
            rehearsal.rehearse_once(env)
    elif case == "after-stamp":
        # Baseline Alembic revision is recorded, but upgrades have not run.
        with patch("flask_migrate.upgrade",
                   side_effect=SyntheticInterruption("AFTER_STAMP")):
            rehearsal.rehearse_once(env)
    elif case == "mid-upgrade":
        # Execute the ACTUAL upgrade to the real immediate predecessor of
        # head, then mimic a process interruption BEFORE the final revision.
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from flask_migrate import upgrade as real_upgrade

        config = Config()
        config.set_main_option(
            "script_location", str(rehearsal.MIGRATION_DIRECTORY)
        )
        previous = ScriptDirectory.from_config(config).get_revision(
            rehearsal.EXPECTED_HEAD
        ).down_revision
        if not isinstance(previous, str) or previous == rehearsal.FRESH_BASELINE:
            raise InterruptedRunDenied("NO_VALID_INTERMEDIATE_REVISION")

        def stop_before_last_revision(*, directory):
            real_upgrade(directory=directory, revision=previous)
            raise SyntheticInterruption("MID_UPGRADE")

        with patch("flask_migrate.upgrade", side_effect=stop_before_last_revision):
            rehearsal.rehearse_once(env)
    elif case == "after-upgrade":
        # Full Alembic already reached head. Inject failure before postcheck.
        with patch.object(
            rehearsal, "_check_post_bootstrap",
            side_effect=SyntheticInterruption("AFTER_UPGRADE"),
        ):
            rehearsal.rehearse_once(env)
    else:
        raise InterruptedRunDenied("INVALID_CASE")


def run(case):
    env = dict(os.environ)
    require_fixture_scope(env)
    if case not in ALLOWED_CASES:
        raise InterruptedRunDenied("UNKNOWN_CASE")
    rehearsal.assert_graph_head()
    create_empty_ci_database(5432)
    cluster = pristine_cluster(5432)
    assert_disposable_clusters(cluster, "7777777777777777777")
    if snapshot()[0]:
        raise InterruptedRunDenied("NOT_FRESH")

    try:
        interrupt_case(env, case)
    except SyntheticInterruption:
        pass
    else:
        raise InterruptedRunDenied("FAULT_WAS_NOT_TRIGGERED")

    verify_lock_is_released()
    before = snapshot()
    if not before[3] or not before[0]:
        raise InterruptedRunDenied("FAILURE_DID_NOT_LEAVE_PARTIAL_SCHEMA")
    if case == "after-models" and before[4]:
        raise InterruptedRunDenied("STAMP_EXECUTED_BEFORE_INJECTION")
    if case == "after-stamp" and before[4] != (rehearsal.FRESH_BASELINE,):
        raise InterruptedRunDenied("BASELINE_NOT_STAMPED")
    if case == "mid-upgrade" and (
        before[4] == (rehearsal.EXPECTED_HEAD,) or not before[4]
    ):
        raise InterruptedRunDenied("MIGRATION_NOT_PARTIAL")
    if case == "after-upgrade" and before[4] != (rehearsal.EXPECTED_HEAD,):
        raise InterruptedRunDenied("FINAL_HEAD_NOT_REACHED")

    try:
        rehearsal.rehearse_once(env)
    except PreflightDenied as exc:
        if exc.code != "NOT_PRISTINE":
            raise InterruptedRunDenied("WRONG_RETRY_DENIAL") from None
    else:
        raise InterruptedRunDenied("SECOND_BOOTSTRAP_WAS_ALLOWED")

    after = snapshot()
    if before != after:
        raise InterruptedRunDenied("RETRY_MUTATED_INTERRUPTED_SCHEMA")
    if pristine_cluster_only_identity() != cluster:
        raise InterruptedRunDenied("TARGET_CLUSTER_CHANGED")

    print(
        "B11D CI PASS: " + case + " interruption retained partial state, "
        "released advisory lock, second initialization refused NOT_PRISTINE, "
        "no auto-repair, disposable PostgreSQL18 only; zero Railway access"
    )


def pristine_cluster_only_identity():
    # The DB is intentionally dirty: query identity, not pristine catalogs.
    conn = psycopg2.connect(
        rehearsal.CI_DSN, connect_timeout=5,
        options="-c default_transaction_read_only=on",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT (pg_catalog.pg_control_system()).system_identifier::text"
            )
            return str(cur.fetchone()[0])
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("B11D CASE REQUIRED")
    run(sys.argv[1])
