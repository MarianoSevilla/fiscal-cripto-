"""S01 LAB: deliberately read-only, one-shot PostgreSQL cluster identity probe.

STG-B10G: this file must never import app.py, models.py, Alembic, Flask,
bootstrap_db.py or payment providers. Even a successful result never authorizes
schema changes or a second executable maintenance entrypoint.
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Mapping

from private_maintenance_preflight import (
    FORBIDDEN_NETWORK_SETTINGS,
    PINNED_IDENTITY,
    PreflightDenied,
    check_pristine_readonly,
    validate_identity,
)

# Captured by owner from Postgres > Database > Query on the isolated S01 lab.
# Neither a password nor TLS peer authentication: a corroborating fingerprint.
EXPECTED_CLUSTER_ID = "7696213098351943739"
IDENTITY_SQL = (
    "SELECT current_database(), current_setting('server_version_num'), "
    "current_setting('transaction_read_only'), "
    "(pg_catalog.pg_control_system()).system_identifier::text"
)


def check_cluster_identity(connection: object) -> str:
    """Reuses an existing connection; no DDL, no schema/data reads."""
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(IDENTITY_SQL)
            row = cur.fetchone()
            if not row or len(row) != 4:
                raise PreflightDenied("CLUSTER_IDENTITY")
            db_name, raw_pg_version, read_only, system_identifier = row
            try:
                version_num = int(raw_pg_version)
            except (ValueError, TypeError):
                raise PreflightDenied("CLUSTER_IDENTITY") from None
            if (
                db_name != "railway"
                or version_num // 10000 != 18
                or read_only != "on"
                or str(system_identifier) != EXPECTED_CLUSTER_ID
            ):
                raise PreflightDenied("CLUSTER_IDENTITY")
            return str(system_identifier)
    finally:
        connection.rollback()


def probe(
    env: Mapping[str, str],
    connect: Callable[..., object],
) -> str:
    """Match pinned S01 Railway identity and DSN BEFORE opening any socket.

    Two catalog reads over the SAME PostgreSQL connection. All transactions
    are READ ONLY, rolled back, and the connection is closed even on failure.
    """
    validate_identity(env, identity=PINNED_IDENTITY)
    dsn = env["DATABASE_URL"]
    if dsn.startswith("postgresql+psycopg2://"):
        dsn = "postgresql://" + dsn[len("postgresql+psycopg2://"):]
    conn = connect(
        dsn,
        connect_timeout=5,
        sslmode="require",
        application_name="s01-lab-readonly-cluster-identity",
        options="-c default_transaction_read_only=on -c statement_timeout=5000",
    )
    try:
        # The earlier B10A preflight is kept unchanged and still mandatory:
        # any relation/function/type/schema/extension or trigger => NO-GO.
        check_pristine_readonly(conn)
        return check_cluster_identity(conn)
    finally:
        conn.close()


def main() -> None:
    try:
        # Any failed project/environment/maintenance service/DSN marker
        # is rejected BEFORE importing psycopg2 and opening the socket.
        validate_identity(os.environ, identity=PINNED_IDENTITY)
        from psycopg2 import connect

        fingerprint = probe(os.environ, connect)
    except PreflightDenied as exc:
        if exc.code == "PUBLIC_NETWORK":
            # Reveal only fixed allowlisted marker NAMES, never secret values.
            markers = ",".join(
                name for name in FORBIDDEN_NETWORK_SETTINGS
                if (os.environ.get(name) or "").strip()
            ) or "UNDETERMINED"
            print("S01 STG-B10G: NO-GO (PUBLIC_NETWORK; markers="
                  + markers + ")", file=sys.stderr, flush=True)
        else:
            print("S01 STG-B10G: NO-GO (" + exc.code + ")",
                  file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        # Driver exceptions may include host/port/username or raw DSNs.
        # Never log stack traces or exception strings in a shared service.
        print("S01 STG-B10G: NO-GO (PROBE_FAILED; details redacted)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print("S01 STG-B10G: PASS (READ ONLY, PostgreSQL18, cluster "
          + fingerprint + ", pristine schema)", flush=True)


if __name__ == "__main__":
    main()
