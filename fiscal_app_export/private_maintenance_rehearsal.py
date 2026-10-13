"""STG-B10C: PostgreSQL 18 bootstrap rehearsal on synthetic GitHub CI ONLY.

No application-server import, no Flask web routes, and no Railway entrypoint.
This is NOT the real lab bootstrap: main() always denies execution. A future
separately approved release must build a different, audited runtime executor.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from private_maintenance_preflight import check_pristine_readonly

# Fixed synthetic CI container destination. Never read DATABASE_URL here.
CI_DSN = "postgresql://postgres:ci-only-test-password@127.0.0.1:5432/railway"
EXPECTED_HEAD = "z9a0b1c2d3e4"
FRESH_BASELINE = "m6n7o8p9q0r1"
LOCK_KEYS = (2026, 1010)
MIGRATION_DIRECTORY = Path(__file__).resolve().parent / "migrations"


class RehearsalDenied(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require_synthetic_ci(env: dict[str, str], dsn: str) -> None:
    """Strict local GitHub Actions fixture scope, never a Railway privilege."""
    if (
        env.get("GITHUB_ACTIONS") != "true"
        or env.get("CI") != "true"
        or env.get("RUNNER_OS") != "Linux"
        or any(key.startswith("RAILWAY_") for key in env)
        or env.get("DATABASE_URL")
        or dsn != CI_DSN
    ):
        raise RehearsalDenied("NOT_SYNTHETIC_CI")
    url = urlsplit(dsn)
    if url.hostname != "127.0.0.1" or url.port != 5432 or url.path != "/railway":
        raise RehearsalDenied("NOT_SYNTHETIC_CI")


def assert_graph_head() -> None:
    """Read only local Alembic files; detect pending multiple/unexpected heads."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATION_DIRECTORY))
    if ScriptDirectory.from_config(cfg).get_heads() != [EXPECTED_HEAD]:
        raise RehearsalDenied("MIGRATION_GRAPH")


def _check_post_bootstrap(conn) -> None:
    """Check head, tables, constraints and indexes; do not repair failures."""
    required_tables = (
        "alembic_version",
        "users",
        "resources",
        "s01_stripe_checkout_attempts",
        "s01_stripe_event_receipts",
        "s01_stripe_notification_outbox",
    )
    required_constraints = (
        "ck_s01_attempt_amount", "ck_s01_attempt_currency",
        "ck_s01_checkout_status", "ck_s01_outbox_kind",
        "ck_s01_outbox_status", "uq_s01_attempt_advisory",
        "uq_s01_outbox_attempt_kind",
    )
    required_indexes = ("ix_s01_attempt_status", "ix_s01_outbox_status")

    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT version_num FROM public.alembic_version")
        if cur.fetchall() != [(EXPECTED_HEAD,)]:
            raise RehearsalDenied("ALEMBIC_HEAD")

        cur.execute(
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = 'public'"
        )
        found = {row[0] for row in cur.fetchall()}
        if not set(required_tables).issubset(found):
            raise RehearsalDenied("TABLES")

        cur.execute(
            "SELECT conname FROM pg_catalog.pg_constraint "
            "WHERE connamespace = 'public'::regnamespace"
        )
        constraints = {row[0] for row in cur.fetchall()}
        if not set(required_constraints).issubset(constraints):
            raise RehearsalDenied("CONSTRAINTS")

        cur.execute(
            "SELECT indexname FROM pg_catalog.pg_indexes "
            "WHERE schemaname = 'public'"
        )
        indexes = {row[0] for row in cur.fetchall()}
        if not set(required_indexes).issubset(indexes):
            raise RehearsalDenied("INDEXES")

        cur.execute(
            "SELECT count(*) FROM public.resources "
            "WHERE slug = 'experimento-bitcoin'"
        )
        if cur.fetchone()[0] != 1:
            raise RehearsalDenied("SEED")
    conn.rollback()


def _minimal_flask_context(dsn: str):
    """Only ORM metadata + Flask-Migrate; NEVER imports app.py."""
    from flask import Flask
    from flask_migrate import Migrate
    from models import db  # models define schema, without web initialization

    app = Flask("synthetic_pg18_rehearsal")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=dsn.replace(
            "postgresql://", "postgresql+psycopg2://", 1
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    Migrate(app, db, directory=str(MIGRATION_DIRECTORY))
    return app, db


def rehearse_once(env: dict[str, str], *, dsn: str = CI_DSN) -> str:
    """Run ONE supervised rehearsal against a strictly fixed CI-local DB.

    Advisory lock spans preflight + ORM + Alembic. Its safety is cooperative;
    it does NOT replace deployment isolation or an approved recovery plan.
    On partial failure the DB is left dirty for inspection; no auto DROP.
    """
    require_synthetic_ci(env, dsn)
    assert_graph_head()

    import psycopg2

    lock_conn = psycopg2.connect(dsn, connect_timeout=5)
    lock_conn.autocommit = True
    acquired = False
    try:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s, %s)", LOCK_KEYS)
            acquired = bool(cur.fetchone()[0])
        if not acquired:
            raise RehearsalDenied("ALREADY_RUNNING")

        preflight_conn = psycopg2.connect(
            dsn, connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=10000",
        )
        try:
            report = check_pristine_readonly(preflight_conn)
            if report.database != "railway" or report.postgres_version // 10000 != 18:
                raise RehearsalDenied("PRECHECK")
        finally:
            preflight_conn.close()

        # Important: fresh ephemeral DB only; no app.py and no Railway.
        from flask_migrate import stamp, upgrade
        app, db = _minimal_flask_context(dsn)
        with app.app_context():
            db.create_all()
            stamp(directory=str(MIGRATION_DIRECTORY), revision=FRESH_BASELINE)
            upgrade(directory=str(MIGRATION_DIRECTORY))

        post_conn = psycopg2.connect(
            dsn, connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=10000",
        )
        try:
            _check_post_bootstrap(post_conn)
        finally:
            post_conn.close()
        return "PASS"
    finally:
        if acquired:
            try:
                with lock_conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s, %s)", LOCK_KEYS)
            finally:
                lock_conn.close()
        else:
            lock_conn.close()


def main() -> None:
    """Intentional NO-GO even on Railway and even with an 'enable' flag."""
    print("S01 STG-B10C: NO-GO (RUNTIME_EXECUTION_NOT_AUTHORIZED)",
          file=sys.stderr, flush=True)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
