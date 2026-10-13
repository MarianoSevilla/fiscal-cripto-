"""G04-R01: six-case legacy S01 financial footprint migration rehearsal.

ONLY GitHub Actions CI with an ephemeral loopback PostgreSQL 18. Never reads
credentials, Railway settings, customer data, files or real service URLs.
Creates synthetic data mirroring ONLY owner-supplied aggregate counts.

This checks the exact DDL of the three S01 Alembic revisions. It is NOT a
substitute for the separately performed restored-backup rehearsal or production
bootstrap. Never import this as an app endpoint or run against Railway.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import runpy

from alembic.migration import MigrationContext
from alembic.operations import Operations
import psycopg2
from psycopg2 import sql
from sqlalchemy import create_engine, inspect, text

from qa_s01_paypal_retirement_pg18 import (
    _admin, _graph, _guard, VERSIONS, REVISIONS,
    PG_USER, PG_PASSWORD, PG_HOST, PG_PORT,
)

DB = "s01_g04_six_case_ci"
BASE_REV = "v5w6x7y8z9a0"
HEAD_REV = "z9a0b1c2d3e4"
NEW_TABLES = (
    "s01_stripe_checkout_attempts",
    "s01_stripe_event_receipts",
    "s01_stripe_notification_outbox",
)
OLD_FIELDS = (
    "id", "status", "paypal_order_id", "paypal_capture_id",
    "stripe_checkout_session_id", "stripe_payment_intent_id",
    "payment_provider", "quoted_amount", "quote_sent_at",
    "quote_expires_at", "quote_accepted_at", "payment_link_token",
    "amount_paid", "paid_at",
)
EXPECTED_COUNTS = (6, 0, 0, 0, 0, 1, 0, 1, 0, 1, 0)


def make_database() -> None:
    with _admin() as conn:
        # CREATE DATABASE requires autocommit and an explicit, local only target.
        conn.autocommit = True
        with conn.cursor() as cur:
            v = cur.execute("SHOW server_version_num")
            n = int(cur.fetchone()[0])
            assert 180000 <= n < 190000, "Expected ephemeral PostgreSQL 18"
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))


def remove_database() -> None:
    with _admin() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(DB)))


def aggregates(conn):
    return tuple(conn.execute(text("""
        SELECT
            COUNT(*),
            COUNT(*) FILTER (WHERE paypal_order_id IS NOT NULL),
            COUNT(*) FILTER (WHERE paypal_capture_id IS NOT NULL),
            COUNT(*) FILTER (WHERE stripe_checkout_session_id IS NOT NULL),
            COUNT(*) FILTER (WHERE stripe_payment_intent_id IS NOT NULL),
            COUNT(*) FILTER (
                WHERE quoted_amount IS NOT NULL OR quote_sent_at IS NOT NULL),
            COUNT(*) FILTER (WHERE quote_accepted_at IS NOT NULL),
            COUNT(*) FILTER (WHERE payment_link_token IS NOT NULL),
            COUNT(*) FILTER (WHERE amount_paid IS NOT NULL OR paid_at IS NOT NULL),
            COUNT(*) FILTER (
                WHERE payment_link_token IS NOT NULL AND status = 'quote_sent'),
            COUNT(*) FILTER (
                WHERE payment_link_token IS NOT NULL AND status = 'quote_sent'
                AND (quote_expires_at IS NULL
                     OR quote_expires_at > TIMESTAMP '2026-10-13 16:00:00')
            )
        FROM fiscal_advisory_requests
    """)).one())


def fingerprint(conn):
    columns = ", ".join(OLD_FIELDS)
    return tuple(conn.execute(text(
        "SELECT " + columns + " FROM fiscal_advisory_requests ORDER BY id"
    )).all())


def main():
    _guard()
    _graph()
    assert os.environ.get("FLASK_ENV") == "testing"
    assert PG_HOST == "127.0.0.1" and PG_PORT == 5432
    assert PG_PASSWORD == "ci-only-test-password"
    # Never build the URL from inherited DATABASE_URL or credentials.
    _admin_conn = _admin()
    try:
        with _admin_conn.cursor() as cur:
            cur.execute("SHOW server_version_num")
            assert 180000 <= int(cur.fetchone()[0]) < 190000
    finally:
        _admin_conn.close()

    make_database()
    engine = create_engine(
        f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{DB}",
        pool_pre_ping=True,
    )
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)
            """))
            conn.execute(text(
                "INSERT INTO alembic_version(version_num) VALUES (:version)"
            ), {"version": BASE_REV})
            conn.execute(text("""
                CREATE TABLE fiscal_advisory_requests (
                    id INTEGER PRIMARY KEY,
                    status VARCHAR(30) NOT NULL,
                    paypal_order_id VARCHAR(64),
                    paypal_capture_id VARCHAR(64),
                    stripe_checkout_session_id VARCHAR(255),
                    stripe_payment_intent_id VARCHAR(255),
                    payment_provider VARCHAR(16),
                    quoted_amount INTEGER,
                    quote_sent_at TIMESTAMP,
                    quote_expires_at TIMESTAMP,
                    quote_accepted_at TIMESTAMP,
                    payment_link_token VARCHAR(64),
                    amount_paid INTEGER,
                    paid_at TIMESTAMP
                )
            """))
            conn.execute(text("""
                INSERT INTO fiscal_advisory_requests (id, status)
                VALUES (1, 'submitted'), (2, 'submitted'),
                       (3, 'submitted'), (4, 'submitted'), (5, 'submitted')
            """))
            conn.execute(text("""
                INSERT INTO fiscal_advisory_requests (
                    id, status, quoted_amount, quote_sent_at,
                    quote_expires_at, payment_link_token
                ) VALUES (
                    6, 'quote_sent', 20000,
                    TIMESTAMP '2026-09-01 12:00:00',
                    TIMESTAMP '2026-10-01 12:00:00',
                    'CI_SYNTHETIC_EXPIRED_TOKEN_NOT_REAL'
                )
            """))
            assert aggregates(conn) == EXPECTED_COUNTS, (
                "Synthetic aggregate scenario does not reproduce user's counts"
            )
            original = fingerprint(conn)
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == BASE_REV
            assert not any(x in inspect(conn).get_table_names() for x in NEW_TABLES)

            migration = MigrationContext.configure(conn)
            with Operations.context(migration):
                for revision, parent, name in REVISIONS:
                    previous = conn.execute(text(
                        "SELECT version_num FROM alembic_version"
                    )).scalar_one()
                    assert previous == parent, "Migration chain is not linear"
                    # Same upgrade() code Alembic invokes, with real DDL in PG18.
                    runpy.run_path(str(VERSIONS / name))["upgrade"]()
                    conn.execute(text("""
                        UPDATE alembic_version
                        SET version_num = :new_rev
                        WHERE version_num = :old_rev
                    """), {"new_rev": revision, "old_rev": parent})
                    assert conn.execute(text(
                        "SELECT version_num FROM alembic_version"
                    )).scalar_one() == revision

            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD_REV
            assert fingerprint(conn) == original, "Historical S01 records changed"
            assert aggregates(conn) == EXPECTED_COUNTS, "Financial aggregate footprint drifted"
            assert len(fingerprint(conn)) == 6, "Historical records were added or lost"

            cols = {c["name"] for c in inspect(conn).get_columns("fiscal_advisory_requests")}
            assert {"rafa_fee_cents", "commission_cents", "commission_rate_bps"} <= cols
            assert conn.execute(text("""
                SELECT COUNT(*) FROM fiscal_advisory_requests
                WHERE rafa_fee_cents IS NOT NULL
                   OR commission_cents IS NOT NULL
                   OR commission_rate_bps IS NOT NULL
            """)).scalar_one() == 0, "Fabricated fees on legacy cases"

            for table in NEW_TABLES:
                assert table in inspect(conn).get_table_names()
                assert conn.execute(text(
                    "SELECT COUNT(*) FROM " + table
                )).scalar_one() == 0, "Unexpected synthetic financial table backfill"

            expected_checks = {
                "ck_s01_attempt_amount",
                "ck_s01_attempt_currency",
                "ck_s01_checkout_status",
            }
            checks = set(conn.execute(text("""
                SELECT conname FROM pg_constraint
                WHERE conrelid =
                  'public.s01_stripe_checkout_attempts'::regclass
                  AND contype = 'c'
            """)).scalars())
            assert expected_checks <= checks
            indexes = set(conn.execute(text("""
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'public'
                AND tablename IN (
                    's01_stripe_checkout_attempts',
                    's01_stripe_notification_outbox'
                )
            """)).scalars())
            assert {"ix_s01_attempt_status", "ix_s01_outbox_status"} <= indexes

        # Commit the isolated test database, reopen, and verify durability.
        with engine.connect() as conn:
            assert aggregates(conn) == EXPECTED_COUNTS
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD_REV
        print(
            "S01 G04 six-case PG18: v5->z9 chain PASS; "
            "six old rows unchanged PASS; one expired quote token unchanged PASS; "
            "zero payment/PayPal/Stripe IDs PASS; no fee backfill PASS; "
            "three financial tables empty PASS; named CHECKs/indexes PASS",
            flush=True,
        )
    finally:
        engine.dispose()
        remove_database()


if __name__ == "__main__":
    main()
