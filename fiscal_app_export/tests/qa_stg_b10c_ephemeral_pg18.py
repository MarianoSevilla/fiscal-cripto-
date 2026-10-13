"""Real PG18 rehearsal ONLY in a brand new disposable GitHub Actions service.

Creates the database `railway` in the job-local Postgres container (not Railway).
The credentials here are intentionally synthetic and fixed in the CI workflow.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Direct script execution sets sys.path[0] to tests/; locate its parent safely.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
from psycopg2 import errors

from private_maintenance_rehearsal import (
    CI_DSN, RehearsalDenied, rehearse_once, require_synthetic_ci,
)


def main():
    env = dict(os.environ)
    require_synthetic_ci(env, CI_DSN)
    # Scope must be verified BEFORE attempting even the synthetic DB creation.
    administration = psycopg2.connect(
        "postgresql://postgres:ci-only-test-password@127.0.0.1:5432/postgres",
        connect_timeout=5,
    )
    administration.autocommit = True
    try:
        with administration.cursor() as cur:
            cur.execute("SELECT datname FROM pg_database WHERE datname = 'railway'")
            if cur.fetchone() is not None:
                raise RehearsalDenied("EPHEMERAL_DATABASE_ALREADY_EXISTS")
            cur.execute("CREATE DATABASE railway")
    finally:
        administration.close()

    assert rehearse_once(env) == "PASS"
    try:
        rehearse_once(env)
    except Exception as exc:
        # Second initialization must refuse BEFORE ORM, stamping or upgrade.
        # The public database contains tables after a successful first run.
        from private_maintenance_preflight import PreflightDenied
        if not isinstance(exc, PreflightDenied) or exc.code != "NOT_PRISTINE":
            raise AssertionError("Second run failed for the wrong reason") from None
    else:
        raise AssertionError("A second initialization unexpectedly succeeded")

    print("B10C CI: first fresh bootstrap PASS; Alembic/head/S01 "
          "integrity PASS; second execution DENIED; no Railway traffic")


if __name__ == "__main__":
    main()
