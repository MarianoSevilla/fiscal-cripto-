"""SEC5-PRIV: executable PostgreSQL 18 isolation pilot, synthetic data ONLY.

This executable is deliberately not imported by Flask, has no HTTP endpoint,
does not run migrations, and refuses execution outside the dedicated CI job.
It demonstrates an actual DB privilege boundary; it does NOT implement or
certify article 32 LOPDGDD across the production application's 17 tables.

No production URLs, records, Stripe, Gmail, email, or real data.
"""
import os

import psycopg2
from psycopg2 import errors, sql


HOST = "127.0.0.1"
DATABASE = "postgres"
DB_USER = "postgres"
CI_PASSWORD = "ci-only-test-password"
APP_SCHEMA = "sec5_priv_pilot_app"
VAULT_SCHEMA = "sec5_priv_pilot_vault"
APP_ROLE = "sec5_priv_pilot_runtime"
LEGAL_ROLE = "sec5_priv_pilot_exception"


def connect():
    return psycopg2.connect(
        host=HOST, port=5432, dbname=DATABASE,
        user=DB_USER, password=CI_PASSWORD, connect_timeout=5,
        options="-c statement_timeout=5000",
    )


def _assert_synthetic_environment():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("SEC5_PRIV_PILOT_ONLY") != "1"
            or os.environ.get("FLASK_ENV") != "testing"):
        raise RuntimeError("SEC5_PRIV PILOT: CI-only gate is closed")
    with connect() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT current_setting('server_version_num')::int")
        version = cursor.fetchone()[0]
        if version // 10000 != 18:
            raise RuntimeError("SEC5_PRIV PILOT: only disposable PostgreSQL 18")
        cursor.execute("SELECT inet_server_addr()::text")
        if cursor.fetchone()[0] not in ("127.0.0.1", "::1"):
            raise RuntimeError("SEC5_PRIV PILOT: unexpected database host")


def setup_synthetic_store():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(APP_ROLE)))
        cur.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(LEGAL_ROLE)))
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(APP_SCHEMA)))
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(VAULT_SCHEMA)))
        cur.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(VAULT_SCHEMA)))
        cur.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(APP_SCHEMA)))
        cur.execute(sql.SQL("""
            CREATE TABLE {}.contacts (
                id BIGSERIAL PRIMARY KEY,
                email TEXT,
                message TEXT,
                status TEXT NOT NULL CHECK (status IN ('active', 'blocked'))
            )
        """).format(sql.Identifier(APP_SCHEMA)))
        cur.execute(sql.SQL("""
            CREATE TABLE {}.blocked_contact_evidence (
                id BIGINT PRIMARY KEY,
                email TEXT NOT NULL,
                message TEXT NOT NULL,
                blocking_cause TEXT NOT NULL,
                blocked_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
            )
        """).format(sql.Identifier(VAULT_SCHEMA)))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
            sql.Identifier(APP_SCHEMA), sql.Identifier(APP_ROLE)))
        cur.execute(sql.SQL("GRANT SELECT ON {}.contacts TO {}").format(
            sql.Identifier(APP_SCHEMA), sql.Identifier(APP_ROLE)))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
            sql.Identifier(VAULT_SCHEMA), sql.Identifier(LEGAL_ROLE)))
        cur.execute(sql.SQL("GRANT SELECT ON {}.blocked_contact_evidence TO {}").format(
            sql.Identifier(VAULT_SCHEMA), sql.Identifier(LEGAL_ROLE)))


def seed_synthetic_contacts():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("""
            INSERT INTO {}.contacts(email, message, status)
            VALUES (%s, %s, 'active'), (%s, %s, 'active'), (%s, %s, 'active')
            RETURNING id
        """).format(sql.Identifier(APP_SCHEMA)), (
            "subject_a@example.invalid", "Synthetic test message A",
            "subject_b@example.invalid", "Synthetic test message B",
            "subject_c@example.invalid", "Synthetic test message C",
        ))
        return [row[0] for row in cur.fetchall()]


def block_synthetic_contact(record_id, *, manual_decision, inject_failure=False):
    """Move ONLY a reviewed synthetic row and redact its ordinary representation.

    The two writes are atomic. The decision string is a test-only gate:
    it is NOT an approval workflow or production legal finding.
    """
    if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id <= 0:
        raise ValueError("unverified record ID")
    if manual_decision != "SYNTHETIC_MANUALLY_REVIEWED":
        raise PermissionError("a positive manual decision is required")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("""
            SELECT email, message, status FROM {}.contacts
            WHERE id = %s FOR UPDATE
        """).format(sql.Identifier(APP_SCHEMA)), (record_id,))
        row = cur.fetchone()
        if row is None:
            raise LookupError("record not found")
        email, message, status = row
        if status == "blocked":
            cur.execute(sql.SQL("""
                SELECT COUNT(*) FROM {}.blocked_contact_evidence WHERE id = %s
            """).format(sql.Identifier(VAULT_SCHEMA)), (record_id,))
            if cur.fetchone()[0] != 1 or email is not None or message is not None:
                raise RuntimeError("inconsistent blocking state")
            return False
        if not email or not message:
            raise RuntimeError("unexpected incomplete source record")

        cur.execute(sql.SQL("""
            INSERT INTO {}.blocked_contact_evidence
                (id, email, message, blocking_cause)
            VALUES (%s, %s, %s, %s)
        """).format(sql.Identifier(VAULT_SCHEMA)), (
            record_id, email, message, "synthetic_exception_example"
        ))
        if inject_failure:
            raise RuntimeError("synthetic crash between two statements")
        cur.execute(sql.SQL("""
            UPDATE {}.contacts
            SET email = NULL, message = NULL, status = 'blocked'
            WHERE id = %s AND status = 'active'
        """).format(sql.Identifier(APP_SCHEMA)), (record_id,))
        if cur.rowcount != 1:
            raise RuntimeError("unexpected concurrent mutation")
        return True


def read_as_role(role, statement, parameters=()):
    """SQL role is lower-privilege despite superuser test connection."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
        cur.execute(statement, parameters)
        return cur.fetchall()


def assert_private_boundary(ids):
    a, b, c = ids
    # Ordinary runtime can query the public projection: blocked PII is NULL.
    rows = read_as_role(APP_ROLE, sql.SQL("""
        SELECT id, email, message, status FROM {}.contacts ORDER BY id
    """).format(sql.Identifier(APP_SCHEMA)))
    assert rows[0] == (a, None, None, "blocked")
    assert rows[1] == (b, "subject_b@example.invalid", "Synthetic test message B", "active")
    assert rows[2] == (c, "subject_c@example.invalid", "Synthetic test message C", "active")
    # An app role must not be allowed SELECT on the vault.
    try:
        read_as_role(APP_ROLE, sql.SQL("""
            SELECT id, email FROM {}.blocked_contact_evidence
        """).format(sql.Identifier(VAULT_SCHEMA)))
    except errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError("ordinary runtime can read blocked personal data")
    # Separate exceptional role CAN read the evidence but cannot write it.
    legal_rows = read_as_role(LEGAL_ROLE, sql.SQL("""
        SELECT id, email FROM {}.blocked_contact_evidence ORDER BY id
    """).format(sql.Identifier(VAULT_SCHEMA)))
    assert legal_rows == [(a, "subject_a@example.invalid")]
    try:
        read_as_role(LEGAL_ROLE, sql.SQL("""
            UPDATE {}.blocked_contact_evidence
            SET message = %s WHERE id = %s RETURNING id
        """).format(sql.Identifier(VAULT_SCHEMA)), ("changed", a))
    except errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError("exception reader can mutate retained evidence")


def teardown_synthetic_store():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(APP_SCHEMA)))
        cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(VAULT_SCHEMA)))
        cur.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(APP_ROLE)))
        cur.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(LEGAL_ROLE)))


def main():
    _assert_synthetic_environment()
    try:
        setup_synthetic_store()
        a, b, c = seed_synthetic_contacts()

        for decision in (None, "", "LEGAL_BLOCK_APPROVED"):
            try:
                block_synthetic_contact(a, manual_decision=decision)
            except PermissionError:
                pass
            else:
                raise AssertionError("non-synthetic authorisation was accepted")

        # A simulated failure halfway through MUST roll back both changes.
        try:
            block_synthetic_contact(a, manual_decision="SYNTHETIC_MANUALLY_REVIEWED",
                                    inject_failure=True)
        except RuntimeError as exc:
            assert str(exc) == "synthetic crash between two statements"
        else:
            raise AssertionError("injected failure did not stop the transaction")
        with connect() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT status FROM {}.contacts WHERE id = %s").format(
                sql.Identifier(APP_SCHEMA)), (a,))
            assert cur.fetchone()[0] == "active"
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.blocked_contact_evidence").format(
                sql.Identifier(VAULT_SCHEMA)))
            assert cur.fetchone()[0] == 0

        assert block_synthetic_contact(
            a, manual_decision="SYNTHETIC_MANUALLY_REVIEWED"
        ) is True
        assert block_synthetic_contact(
            a, manual_decision="SYNTHETIC_MANUALLY_REVIEWED"
        ) is False  # Idempotent retry
        assert_private_boundary((a, b, c))
        try:
            block_synthetic_contact(9999, manual_decision="SYNTHETIC_MANUALLY_REVIEWED")
        except LookupError:
            pass
        else:
            raise AssertionError("unknown ID was accepted")
        print("SEC5_PRIV_PG18_PILOT: PASS")
    finally:
        teardown_synthetic_store()


if __name__ == "__main__":
    main()
