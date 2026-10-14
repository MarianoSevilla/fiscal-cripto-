"""STG-B11A: empty-backup -> independent PG18 -> bootstrap, GitHub CI ONLY.

Two disposable local PostgreSQL18 containers:
  - source 127.0.0.1:55433, empty database 'railway'
  - destination 127.0.0.1:5432, restored then bootstrapped
This script contains NO Railway credentials, hostnames, imports of app.py,
or real-lab entrypoint. Never run with Railway credentials or source data.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
from private_maintenance_preflight import (
    PreflightDenied,
    check_pristine_readonly,
)
from private_maintenance_rehearsal import (
    CI_DSN, RehearsalDenied, assert_graph_head, rehearse_once,
    require_synthetic_ci,
)

SOURCE_PORT = 55433
DESTINATION_PORT = 5432
DATABASE = "railway"
CI_PASSWORD = "ci-only-test-password"
FORBIDDEN_REAL_CLUSTERS = frozenset((
    "7696213098351943739",
    "7696517018472497211",
))


def require_fixture_scope(env: dict[str, str]) -> None:
    require_synthetic_ci(env, CI_DSN)
    if any(env.get(name) for name in (
        "TARGET_DATABASE_URL", "SOURCE_DATABASE_URL", "PGHOST",
        "PGSERVICE", "PGPASSFILE", "PGPASSWORD",
    )):
        raise RehearsalDenied("EXTERNAL_DATABASE_VARIABLE")
    if env.get("S01_RECOVERY_WRITE_APPROVAL"):
        raise RehearsalDenied("WRITE_APPROVAL_OUT_OF_SCOPE")
    if env.get("B11A_RESTORE_REAL_BACKUP"):
        raise RehearsalDenied("REAL_BACKUP_OUT_OF_SCOPE")


def assert_disposable_clusters(source: str, target: str) -> None:
    ids = (source, target)
    if any(not val.isdecimal() or len(val) < 16 or len(val) > 20
           for val in ids):
        raise RehearsalDenied("CLUSTER_FORMAT")
    if source == target or any(val in FORBIDDEN_REAL_CLUSTERS for val in ids):
        raise RehearsalDenied("NOT_DISTINCT_DISPOSABLE_CLUSTERS")


def dsn(port: int, database: str = DATABASE) -> str:
    if port not in (SOURCE_PORT, DESTINATION_PORT):
        raise RehearsalDenied("UNAPPROVED_CI_PORT")
    if database not in ("postgres", DATABASE):
        raise RehearsalDenied("UNAPPROVED_CI_DB")
    return (
        "postgresql://postgres:" + CI_PASSWORD
        + "@127.0.0.1:" + str(port) + "/" + database
    )


def create_empty_ci_database(port: int):
    conn = psycopg2.connect(dsn(port, "postgres"), connect_timeout=5)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s",
                (DATABASE,),
            )
            if cur.fetchone() is not None:
                raise RehearsalDenied("CI_DATABASE_ALREADY_EXISTS")
            cur.execute("CREATE DATABASE railway")
    finally:
        conn.close()


def pristine_cluster(port: int) -> str:
    connection = psycopg2.connect(
        dsn(port), connect_timeout=5, sslmode="prefer",
        options="-c default_transaction_read_only=on -c statement_timeout=10000",
    )
    try:
        result = check_pristine_readonly(connection)
        if result.database != DATABASE or result.postgres_version // 10000 != 18:
            raise RehearsalDenied("CI_NOT_PG18")
        with connection.cursor() as cur:
            cur.execute(
                "SELECT (pg_catalog.pg_control_system()).system_identifier::text"
            )
            row = cur.fetchone()
        connection.rollback()
        if row is None or len(row) != 1:
            raise RehearsalDenied("CI_NO_CLUSTER_ID")
        return str(row[0])
    finally:
        connection.close()


def run_pg_cli(args: list[str], folder: Path):
    # Independent disposable docker postgres:18 client, pinned IP/ports and
    # fully synthetic CI credentials. Never access Railway service names.
    command = [
        "docker", "run", "--rm", "--network", "host",
        "-e", "PGPASSWORD=" + CI_PASSWORD,
        "-v", str(folder) + ":/backup",
        "postgres:18",
        *args,
    ]
    result = subprocess.run(
        command, text=True, capture_output=True, check=False, timeout=80
    )
    if result.returncode:
        # Never expose SQL/server client logs, even for CI.
        raise RehearsalDenied("CI_PGDUMP_OR_RESTORE_FAILED")


def run() -> None:
    env = dict(os.environ)
    require_fixture_scope(env)
    assert_graph_head()
    create_empty_ci_database(SOURCE_PORT)
    create_empty_ci_database(DESTINATION_PORT)
    source_id = pristine_cluster(SOURCE_PORT)
    destination_id = pristine_cluster(DESTINATION_PORT)
    assert_disposable_clusters(source_id, destination_id)

    with TemporaryDirectory(prefix="s01-b11a-restored-ci-") as tmp:
        archive = Path(tmp) / "empty-synthetic-pg18.pgcustom"
        run_pg_cli([
            "pg_dump", "-Fc", "--no-owner", "--no-acl",
            "-h", "127.0.0.1", "-p", str(SOURCE_PORT),
            "-U", "postgres", "-d", DATABASE,
            "-f", "/backup/" + archive.name,
        ], Path(tmp))
        if not archive.exists() or archive.stat().st_size < 5:
            raise RehearsalDenied("CI_ARCHIVE_EMPTY")
        if archive.open("rb").read(5) != b"PGDMP":
            raise RehearsalDenied("CI_ARCHIVE_NOT_CUSTOM")
        run_pg_cli([
            "pg_restore", "--single-transaction", "--exit-on-error",
            "--no-owner", "--no-acl",
            "-h", "127.0.0.1", "-p", str(DESTINATION_PORT),
            "-U", "postgres", "-d", DATABASE,
            "/backup/" + archive.name,
        ], Path(tmp))
    if pristine_cluster(DESTINATION_PORT) != destination_id:
        raise RehearsalDenied("CI_TARGET_ID_CHANGED")
    if pristine_cluster(SOURCE_PORT) != source_id:
        raise RehearsalDenied("CI_SOURCE_CHANGED")

    # Actual SQLAlchemy metadata creation + Alembic stamped-baseline and
    # upgrade sequence executes on the restored CI-target only.
    if rehearse_once(env) != "PASS":
        raise RehearsalDenied("CI_BOOTSTRAP_RESULT")

    # A repeated attempt must not apply another migration or seed.
    try:
        rehearse_once(env)
    except PreflightDenied as exc:
        if exc.code != "NOT_PRISTINE":
            raise RehearsalDenied("CI_REPLAY_WRONG_REASON") from None
    else:
        raise RehearsalDenied("CI_REPLAY_UNEXPECTEDLY_ALLOWED")

    if pristine_cluster(SOURCE_PORT) != source_id:
        raise RehearsalDenied("CI_BACKUP_SOURCE_MODIFIED")
    print(
        "B11A CI PASS: empty pg_dump restored on distinct PG18 target; "
        "full S01 metadata+Alembic bootstrap to pinned head succeeded; "
        "second bootstrap denied; separate source stayed pristine; "
        "no Railway access.",
        flush=True,
    )


if __name__ == "__main__":
    run()
