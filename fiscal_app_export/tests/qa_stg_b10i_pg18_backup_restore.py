"""STG-B10I: inspect TWO disposable PostgreSQL18 clusters in GitHub CI.

setup: create blank 'railway' DB on source and target, and bootstrap source.
verify: prove restoration into independent cluster, with matching schema/data.

The actual dump and restore are performed by the GitHub Actions workflow
using PostgreSQL 18 client containers. No Railway service, URL or credentials
can be provided to this script.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg2
from psycopg2 import sql

from private_maintenance_rehearsal import (
    CI_DSN, _check_post_bootstrap, rehearse_once, require_synthetic_ci,
)

SOURCE_DSN = CI_DSN
TARGET_DSN = (
    "postgresql://postgres:ci-only-test-password@127.0.0.1:55433/railway"
)
SOURCE_ADMIN_DSN = SOURCE_DSN.replace("/railway", "/postgres")
TARGET_ADMIN_DSN = TARGET_DSN.replace("/railway", "/postgres")
LIVE_LAB_CLUSTER = "7696213098351943739"


def assert_ci_only() -> dict[str, str]:
    env = dict(os.environ)
    require_synthetic_ci(env, SOURCE_DSN)
    if os.environ.get("PGHOST") or os.environ.get("PGSERVICE"):
        raise RuntimeError("Unexpected Postgres host override")
    if not TARGET_DSN.endswith("@127.0.0.1:55433/railway"):
        raise RuntimeError("Unexpected fixture destination")
    return env


def create_blank_database(admin_dsn: str) -> None:
    conn = psycopg2.connect(admin_dsn, connect_timeout=5)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = 'railway'")
            if cursor.fetchone() is not None:
                raise AssertionError("Fixture database pre-exists: NO-GO")
            cursor.execute("CREATE DATABASE railway")
    finally:
        conn.close()


def fingerprint(dsn: str) -> tuple:
    conn = psycopg2.connect(
        dsn, connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=10000"
    )
    try:
        _check_post_bootstrap(conn)
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(
                "SELECT current_database(), current_setting('server_version_num'), "
                "(pg_catalog.pg_control_system()).system_identifier::text"
            )
            database, version, cluster_id = cur.fetchone()
            if database != "railway" or int(version) // 10000 != 18:
                raise AssertionError("Not the synthetic PG18 railway DB")
            if cluster_id == LIVE_LAB_CLUSTER:
                raise AssertionError("Prohibited: cluster matches LIVE S01 lab")
            cur.execute(
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
            tables = [row[0] for row in cur.fetchall()]
            row_counts = []
            for table in tables:
                cur.execute(
                    sql.SQL("SELECT count(*) FROM public.{}").format(
                        sql.Identifier(table)
                    )
                )
                row_counts.append((table, cur.fetchone()[0]))
            cur.execute(
                "SELECT slug, title FROM public.resources ORDER BY slug"
            )
            resources = tuple(cur.fetchall())
            cur.execute(
                "SELECT c.conname, pg_catalog.pg_get_constraintdef(c.oid) "
                "FROM pg_catalog.pg_constraint c "
                "JOIN pg_catalog.pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname='public' ORDER BY c.conname"
            )
            constraints = tuple(cur.fetchall())
            cur.execute(
                "SELECT tablename, indexname, indexdef "
                "FROM pg_catalog.pg_indexes WHERE schemaname='public' "
                "ORDER BY tablename, indexname"
            )
            indexes = tuple(cur.fetchall())
            return (
                str(cluster_id), tuple(tables), tuple(row_counts),
                resources, constraints, indexes
            )
    finally:
        conn.rollback()
        conn.close()


def main() -> None:
    env = assert_ci_only()
    if len(sys.argv) != 2 or sys.argv[1] not in ("setup", "verify"):
        raise SystemExit("Synthetic CI mode required: setup or verify")

    if sys.argv[1] == "setup":
        create_blank_database(SOURCE_ADMIN_DSN)
        create_blank_database(TARGET_ADMIN_DSN)
        if rehearse_once(env) != "PASS":
            raise AssertionError("PG18 synthetic source bootstrap failed")
        source = fingerprint(SOURCE_DSN)
        print(
            "S01 B10I SETUP PASS: synthetic source PG18 populated; "
            "separate target DB empty, no Railway access",
            flush=True,
        )
        return

    source = fingerprint(SOURCE_DSN)
    target = fingerprint(TARGET_DSN)
    if source[0] == target[0]:
        raise AssertionError("Recovery target is not an independent cluster")
    if source[1:] != target[1:]:
        raise AssertionError("Logical restore differs from source schema/data")
    if len(source[1]) < 10:
        raise AssertionError("Restored table count unexpectedly small")
    print(
        "S01 B10I RESTORE PASS: two independent PostgreSQL18 clusters; "
        "Alembic head, all table counts, indexes, constraints and "
        "seeded synthetic resources match; no Railway writes",
        flush=True,
    )


if __name__ == "__main__":
    main()
