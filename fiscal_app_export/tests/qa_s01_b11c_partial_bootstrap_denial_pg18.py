"""STG-B11C: prove actual bootstrap rejects partial and busy PostgreSQL18.

GitHub Actions disposable localhost fixture only. Never connects to Railway,
uses a production DSN, imports the web application, or repairs user data.
A partial/ambiguous database is deliberately LEFT UNTOUCHED after denial.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
from private_maintenance_preflight import PreflightDenied
from private_maintenance_rehearsal import (
    CI_DSN, LOCK_KEYS, RehearsalDenied, assert_graph_head,
    rehearse_once,
)
from qa_s01_b11a_restored_bootstrap_pg18 import (
    FORBIDDEN_REAL_CLUSTERS, assert_disposable_clusters,
    create_empty_ci_database, require_fixture_scope,
)

ADMIN_DSN = (
    "postgresql://postgres:ci-only-test-password"
    "@127.0.0.1:5432/postgres"
)
FIXTURES = (
    ("partial_user_table",
     "CREATE TABLE public.partial_ci_probe (id integer PRIMARY KEY); "
     "INSERT INTO public.partial_ci_probe (id) VALUES (123);",
     "DROP TABLE public.partial_ci_probe",
     "SELECT count(*) FROM public.partial_ci_probe"),
    ("unversioned_alembic",
     "CREATE TABLE public.alembic_version (version_num varchar(32) NOT NULL);",
     "DROP TABLE public.alembic_version",
     "SELECT count(*) FROM public.alembic_version"),
    ("unplanned_schema",
     "CREATE SCHEMA unexpected_ci;",
     "DROP SCHEMA unexpected_ci",
     "SELECT count(*) FROM pg_catalog.pg_namespace "
     "WHERE nspname='unexpected_ci'"),
    ("public_function",
     "CREATE FUNCTION public.partial_ci_function() RETURNS integer "
     "LANGUAGE SQL AS 'SELECT 1';",
     "DROP FUNCTION public.partial_ci_function()",
     "SELECT count(*) FROM pg_catalog.pg_proc p JOIN "
     "pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
     "WHERE n.nspname='public' AND p.proname='partial_ci_function'"),
)


def query(dsn: str, sql: str):
    with psycopg2.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            if cursor.description:
                return cursor.fetchone()[0]
    return None


def require_disposable_target():
    admin = psycopg2.connect(ADMIN_DSN, connect_timeout=5)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT datname FROM pg_catalog.pg_database WHERE datname='railway'"
            )
            if cursor.fetchone() is not None:
                raise RehearsalDenied("NON_FRESH_TARGET")
    finally:
        admin.close()

    create_empty_ci_database(5432)
    cluster = str(query(
        CI_DSN, "SELECT (pg_catalog.pg_control_system()).system_identifier::text"
    ))
    if cluster in FORBIDDEN_REAL_CLUSTERS or not cluster.isdecimal():
        raise RehearsalDenied("REAL_CLUSTER_DENIED")
    # Validate format without allowing either real S01 identifier.
    assert_disposable_clusters(cluster, "7777777777777777777")
    return cluster


def expect_refusal(env: dict[str, str], expected_code: str):
    try:
        rehearse_once(env)
    except PreflightDenied as exc:
        if exc.code != expected_code:
            raise RehearsalDenied("WRONG_PREFLIGHT_REFUSAL") from None
    except RehearsalDenied as exc:
        if exc.code != expected_code:
            raise RehearsalDenied("WRONG_REHEARSAL_REFUSAL") from None
    else:
        raise RehearsalDenied("UNSAFE_BOOTSTRAP_ACCEPTED")


def public_table_snapshot() -> list[str]:
    conn = psycopg2.connect(
        CI_DSN, connect_timeout=5,
        options="-c default_transaction_read_only=on",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname='public' ORDER BY tablename"
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.rollback()
        conn.close()


def run():
    env = dict(os.environ)
    require_fixture_scope(env)
    assert_graph_head()
    cluster = require_disposable_target()

    # Every fixture starts pristine. Create exactly one unexpected object,
    # invoke the same bootstrap logic B10C/B11A exercises, and prove neither
    # Alembic nor ORM attempted to complete or repair anything.
    for name, setup_sql, cleanup_sql, object_check in FIXTURES:
        if public_table_snapshot():
            raise RehearsalDenied("FIXTURE_NOT_EMPTY")
        query(CI_DSN, setup_sql)
        before_tables = public_table_snapshot()
        before_value = query(CI_DSN, object_check)
        expect_refusal(env, "NOT_PRISTINE")
        after_tables = public_table_snapshot()
        after_value = query(CI_DSN, object_check)
        if before_tables != after_tables or before_value != after_value:
            raise RehearsalDenied("UNEXPECTED_PARTIAL_WRITE")
        if query(CI_DSN, "SELECT to_regclass('public.users') IS NULL") is not True:
            raise RehearsalDenied("UNAUTHORIZED_MODELS_CREATED")
        query(CI_DSN, cleanup_sql)
        if public_table_snapshot():
            raise RehearsalDenied("FIXTURE_LEFT_OBJECTS")
        print("B11C CI " + name + ": NOT_PRISTINE, no repair and no extra objects")

    # Advisory-lock conflict must deny even a truly pristine target.
    lock = psycopg2.connect(CI_DSN, connect_timeout=5)
    lock.autocommit = True
    try:
        with lock.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s,%s)", LOCK_KEYS)
            if not cur.fetchone()[0]:
                raise RehearsalDenied("CI_LOCK_NOT_ACQUIRED")
        before = public_table_snapshot()
        expect_refusal(env, "ALREADY_RUNNING")
        if before != public_table_snapshot():
            raise RehearsalDenied("LOCK_DENIAL_WROTE_SCHEMA")
    finally:
        with lock.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s,%s)", LOCK_KEYS)
        lock.close()

    # Must still be the disposable cluster and pristine after every denial.
    final = str(query(
        CI_DSN, "SELECT (pg_catalog.pg_control_system()).system_identifier::text"
    ))
    if final != cluster or public_table_snapshot():
        raise RehearsalDenied("CI_TARGET_CHANGED")
    if query(CI_DSN, "SELECT to_regclass('public.alembic_version') IS NULL") is not True:
        raise RehearsalDenied("ALEMBIC_WAS_STAMPED")

    print(
        "B11C CI PASS: four partial/unversioned fixtures and advisory lock "
        "fail closed, no ORM tables, no Alembic stamp or repair, disposable PG18 only"
    )


if __name__ == "__main__":
    run()
