"""CI-only S01 PayPal-retirement migration audit against ephemeral PostgreSQL 18.

Tests DDL of three S01 migrations against a small, populated historical
advisory table. NOT a rehearsal of Railway's actual full production migration.
Never accepts DATABASE_URL or credentials from the environment.
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path

import psycopg2
from psycopg2 import sql
from sqlalchemy import create_engine, text, inspect
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "migrations" / "versions"
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASSWORD = "ci-only-test-password"
DB = "s01_paypal_retirement_ci"
PROD_HEAD = "v5w6x7y8z9a0"
REVISIONS = (
    ("x7y8z9a0b1c2", PROD_HEAD,
     "x7y8z9a0b1c2_s01_quote_breakdown.py"),
    ("y8z9a0b1c2d3", "x7y8z9a0b1c2",
     "y8z9a0b1c2d3_s01_checkout_attempts.py"),
    ("z9a0b1c2d3e4", "y8z9a0b1c2d3",
     "z9a0b1c2d3e4_s01_notification_outbox.py"),
)


def _guard():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("CI") != "true"
            or os.environ.get("FLASK_ENV") != "testing"):
        raise RuntimeError("Solo se permite en CI de GitHub sin conexión externa")


def _admin():
    _guard()
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, dbname="postgres", connect_timeout=5,
    )


def _graph():
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = tuple(script.get_heads())
    assert heads == ("z9a0b1c2d3e4",), (
        f"Se requiere un solo Alembic head S01: {heads!r}"
    )
    known = {rev.revision for rev in script.walk_revisions()}
    assert "w6x7y8z9a0b1" not in known, (
        "U04 PayPal #29 no puede incorporarse implícitamente a S01"
    )
    for rev, parent, filename in REVISIONS:
        node = script.get_revision(rev)
        assert node is not None
        assert node.down_revision == parent
        assert (VERSIONS / filename).is_file()
    assert script.get_revision(PROD_HEAD) is not None


def _make_db():
    conn = _admin()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version_num')::integer")
            n = cur.fetchone()[0]
            if not 180000 <= n < 190000:
                raise AssertionError(f"Exige PostgreSQL 18, detectado {n}")
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
    finally:
        conn.close()


def _drop_db():
    conn = _admin()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(DB)))
    finally:
        conn.close()


def main():
    _guard()
    _graph()
    _make_db()
    url = (
        f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@"
        f"{PG_HOST}:{PG_PORT}/{DB}"
    )
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            # Schema sintético mínimo ANTERIOR a S01: datos de PayPal
            # intencionalmente retenidos y sin necesidad de importar app.py.
            conn.execute(text("""
                CREATE TABLE fiscal_advisory_requests (
                    id INTEGER PRIMARY KEY,
                    paypal_order_id VARCHAR(64),
                    paypal_capture_id VARCHAR(64),
                    payment_provider VARCHAR(16),
                    status VARCHAR(40) NOT NULL,
                    amount_paid INTEGER,
                    payment_link_token VARCHAR(64)
                )
            """))
            conn.execute(text("""
                INSERT INTO fiscal_advisory_requests (
                    id, paypal_order_id, paypal_capture_id, payment_provider,
                    status, amount_paid, payment_link_token
                ) VALUES (
                    1, 'ORDER_SYNTHETIC_HISTORICAL',
                    'CAPTURE_SYNTHETIC_HISTORICAL',
                    'paypal', 'paid_received', 26000,
                    'legacy-token-synthetic'
                )
            """))

            # Ejecutar las operaciones exactas de los tres migrations scripts
            # bajo contexto Alembic contra una transacción PG18 efímera.
            migrator = MigrationContext.configure(conn)
            with Operations.context(migrator):
                for _revision, _parent, filename in REVISIONS:
                    upgrade = runpy.run_path(str(VERSIONS / filename))["upgrade"]
                    upgrade()

            row = conn.execute(text("""
                SELECT paypal_order_id, paypal_capture_id, payment_provider,
                       status, amount_paid, payment_link_token,
                       rafa_fee_cents, commission_cents, commission_rate_bps
                FROM fiscal_advisory_requests WHERE id=1
            """)).one()
            assert tuple(row) == (
                "ORDER_SYNTHETIC_HISTORICAL",
                "CAPTURE_SYNTHETIC_HISTORICAL",
                "paypal", "paid_received", 26000,
                "legacy-token-synthetic",
                None, None, None,
            ), "Se ha alterado evidencia PayPal o inventado un desglose legacy"

            tables = inspect(conn).get_table_names()
            for name in (
                "s01_stripe_checkout_attempts",
                "s01_stripe_event_receipts",
                "s01_stripe_notification_outbox",
            ):
                assert name in tables, f"Falta tabla S01 {name}"

            # G04 regression from Mac backup: with Flask import DDL
            # eliminated, these two named CHECKs MUST be created directly by
            # Alembic, not by SQLAlchemy db.create_all().
            required_check_names = {
                "ck_s01_attempt_amount",
                "ck_s01_attempt_currency",
                "ck_s01_checkout_status",
            }
            actual_checks = set(conn.execute(text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'public.s01_stripe_checkout_attempts'::regclass "
                "AND contype = 'c'"
            )).scalars().all())
            assert required_check_names.issubset(actual_checks), (
                "S01 migration omitted named financial CHECK constraints "
                "required by the no-DDL startup gate"
            )

            assert conn.execute(text(
                "SELECT count(*) FROM s01_stripe_checkout_attempts"
            )).scalar_one() == 0
            assert conn.execute(text(
                "SELECT count(*) FROM s01_stripe_notification_outbox"
            )).scalar_one() == 0

            # Repetir DDL para comprobar la condición idempotente de
            # CREATE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS en el test.
            with Operations.context(migrator):
                for _, _, filename in REVISIONS:
                    runpy.run_path(str(VERSIONS / filename))["upgrade"]()
            preserved = conn.execute(text("""
                SELECT paypal_order_id, paypal_capture_id
                FROM fiscal_advisory_requests WHERE id=1
            """)).one()
            assert tuple(preserved) == (
                "ORDER_SYNTHETIC_HISTORICAL",
                "CAPTURE_SYNTHETIC_HISTORICAL",
            )
        print(
            "S01 migration gate: single linear Alembic head PASS; "
            "U04 PayPal parallel revision absent PASS; legacy order/capture "
            "retained PASS; no fabricated quote backfill PASS; "
            "synthetic PG18 DDL replay PASS; named S01 CHECKs PASS",
            flush=True,
        )
    finally:
        engine.dispose()
        _drop_db()


if __name__ == "__main__":
    main()
