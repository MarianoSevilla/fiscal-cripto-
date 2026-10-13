"""Adversarial S01 rehearsal: isolated GitHub Actions postgres:18 ONLY.

Two modes run in independent ephemeral PostgreSQL containers. No cleanup SQL,
real credentials, Railway runtime, or application-server endpoint is involved.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIR))

import psycopg2

from private_maintenance_preflight import PreflightDenied
from private_maintenance_rehearsal import (
    CI_DSN, LOCK_KEYS, RehearsalDenied, rehearse_once, require_synthetic_ci,
)

ADMIN_DSN = "postgresql://postgres:ci-only-test-password@127.0.0.1:5432/postgres"


def create_disposable_fixture() -> None:
    connection = psycopg2.connect(ADMIN_DSN, connect_timeout=5)
    connection.autocommit = True
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = 'railway'")
            if cur.fetchone():
                raise AssertionError("Ephemeral fixture unexpectedly exists")
            cur.execute("CREATE DATABASE railway")
    finally:
        connection.close()


def relation_count() -> int:
    conn = psycopg2.connect(CI_DSN, connect_timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public'"
            )
            return cur.fetchone()[0]
    finally:
        conn.rollback()
        conn.close()


def run_g04() -> tuple[int, bool, bool]:
    env = dict(os.environ)
    env.update({
        "FLASK_ENV": "production",
        "SECRET_KEY": "CI-ONLY-FAKE-SECRET-NOT-FOR-DEPLOY-12345678",
        "DATABASE_URL": CI_DSN,
        "RESEND_API_KEY": "",
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
    })
    result = subprocess.run(
        [sys.executable, "-c", "from startup_schema_gate import main; main()"],
        cwd=DIR, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=90, check=False,
    )
    # Do not disclose raw DB driver errors even in automated CI assertion logs.
    return (
        result.returncode,
        "S01 G04 STARTUP: PASS" in result.stdout,
        "S01 G04 STARTUP: NO-GO" in result.stdout,
    )


def fault_scenario(env: dict[str, str]) -> None:
    owner = psycopg2.connect(CI_DSN, connect_timeout=5)
    owner.autocommit = True
    try:
        with owner.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s, %s)", LOCK_KEYS)
            if cur.fetchone()[0] is not True:
                raise AssertionError("Fixture advisory lock unavailable")
        try:
            rehearse_once(env)
        except RehearsalDenied as exc:
            if exc.code != "ALREADY_RUNNING":
                raise
        else:
            raise AssertionError("Competing maintenance runner entered DB")
        if relation_count() != 0:
            raise AssertionError("Rejected lock contention wrote schema")
    finally:
        try:
            with owner.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s, %s)", LOCK_KEYS)
                if cur.fetchone()[0] is not True:
                    raise AssertionError("Fixture advisory lock not released")
        finally:
            owner.close()

    # This synthetic fault happens after create_all() and Alembic stamp,
    # before any version upgrades. Database must remain dirty and blocked.
    with patch("flask_migrate.upgrade", side_effect=RuntimeError("CI_INTERRUPT")):
        try:
            rehearse_once(env)
        except RuntimeError as exc:
            if str(exc) != "CI_INTERRUPT":
                raise
        else:
            raise AssertionError("Synthetic failure did not interrupt migration")

    if relation_count() == 0:
        raise AssertionError("Fault injection did not produce partial DB")
    try:
        rehearse_once(env)
    except PreflightDenied as exc:
        if exc.code != "NOT_PRISTINE":
            raise
    else:
        raise AssertionError("Partially initialized DB accepted a retry")

    rc, ok, denied = run_g04()
    if rc == 0 or ok or not denied:
        raise AssertionError("G04 gate accepted a partial synthetic schema")
    print(
        "B10D FAULT PASS: concurrent run denied without DDL; "
        "interrupted migration left partial schema; retry denied; "
        "G04 refused partial schema", flush=True,
    )


def healthy_scenario(env: dict[str, str]) -> None:
    if rehearse_once(env) != "PASS":
        raise AssertionError("Expected clean ephemeral PostgreSQL migration")
    try:
        rehearse_once(env)
    except PreflightDenied as exc:
        if exc.code != "NOT_PRISTINE":
            raise
    else:
        raise AssertionError("Completed schema unexpectedly reinitialized")

    rc, ok, denied = run_g04()
    if rc != 0 or not ok or denied:
        raise AssertionError("G04 gate rejected valid synthetic S01 schema")
    print(
        "B10D HEALTHY PASS: fresh PG18 initialized; second run denied; "
        "independent production-style G04 read-only gate passed", flush=True,
    )


def main() -> None:
    env = dict(os.environ)
    require_synthetic_ci(env, CI_DSN)  # Mandatory before even local fixture I/O.
    if len(sys.argv) != 2 or sys.argv[1] not in ("fault", "healthy"):
        raise SystemExit("Usage: fixture test mode required")
    create_disposable_fixture()
    if sys.argv[1] == "fault":
        fault_scenario(env)
    else:
        healthy_scenario(env)


if __name__ == "__main__":
    main()
