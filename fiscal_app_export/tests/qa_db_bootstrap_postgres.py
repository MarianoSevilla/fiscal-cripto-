"""Real PostgreSQL isolation tests for bootstrap_db.py.

Runs ONLY in the GitHub Actions job with an ephemeral postgres:18 container.
Uses synthetic data and transient test databases; never connects to Railway.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

DIR = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 5432
USER = "postgres"
PASSWORD = "ci-only-test-password"
HEAD = "w6x7y8z9a0b1"


def _create_db(name: str) -> str:
    conn = psycopg2.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD, dbname="postgres"
    )
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        conn.close()
    return name


def _db_conn(name: str):
    return psycopg2.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD, dbname=name
    )


def _env(name: str) -> dict[str, str]:
    result = {k: os.environ[k] for k in ("PATH", "PYTHONPATH", "SYSTEMROOT", "TMPDIR") if k in os.environ}
    result.update({
        "FLASK_ENV": "production",
        "SECRET_KEY": "CI-TEST-ONLY-DO-NOT-USE-IN-PRODUCTION-123",
        "DATABASE_URL": (
            f"postgresql://{USER}:{PASSWORD}@{HOST}:{PORT}/{name}"
        ),
        "RESEND_API_KEY": "",
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
    })
    return result


def _run(name: str, script: str, *, success: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=DIR, env=_env(name), text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=150, check=False,
    )
    if success != (proc.returncode == 0):
        raise AssertionError(
            f"Database={name}, rc={proc.returncode}, expected_success={success}\n"
            + proc.stdout[-6500:]
        )
    return proc


def _bootstrap(name: str, success: bool = True) -> subprocess.CompletedProcess:
    return _run(
        name,
        "from bootstrap_db import main; main()",
        success=success,
    )


def _assert_version(name: str) -> None:
    with _db_conn(name) as conn, conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchall() == [(HEAD,)], "Alembic head mismatch"


def main() -> None:
    # 1. Fresh PostgreSQL: current ORM model tables initially created on import.
    fresh = _create_db("bootstrap_fresh_ci")
    _bootstrap(fresh)
    _assert_version(fresh)
    with _db_conn(fresh) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT headline FROM resources WHERE slug = 'experimento-bitcoin'"
        )
        row = cur.fetchone()
        assert row and row[0], "Legacy seed/data migrations were skipped"

    # 2. Existing, fully versioned database with user data must retain that data.
    _run(fresh, """
from app import app, db
from models import User
with app.app_context():
    db.session.add(User(email="fixture@example.invalid", full_name="Fictitious User"))
    db.session.commit()
""")
    _bootstrap(fresh)
    _assert_version(fresh)
    with _db_conn(fresh) as conn, conn.cursor() as cur:
        cur.execute("SELECT full_name FROM users WHERE email = %s",
                    ("fixture@example.invalid",))
        assert cur.fetchone() == ("Fictitious User",)
        cur.execute("SELECT COUNT(*) FROM resources WHERE slug = 'experimento-bitcoin'")
        assert cur.fetchone()[0] == 1, "Seed duplicated on second boot"

    # 3. Populated but UNVERSIONED database must fail closed; do not stamp it.
    legacy = _create_db("bootstrap_unversioned_ci")
    _run(legacy, """
from app import app, db
from models import User
with app.app_context():
    db.session.add(User(email="existing@example.invalid"))
    db.session.commit()
""")
    failed = _bootstrap(legacy, success=False)
    assert "already contains records" in failed.stdout
    with _db_conn(legacy) as conn, conn.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE email = %s",
                    ("existing@example.invalid",))
        assert cur.fetchone() == ("existing@example.invalid",)
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'alembic_version' AND table_schema='public'"
        )
        # No stamping performed, even though app import creates ORM tables.
        if cur.fetchone()[0]:
            cur.execute("SELECT COUNT(*) FROM alembic_version")
            assert cur.fetchone()[0] == 0

    # 4. Incomplete, UNVERSIONED legacy table must fail closed, even if empty.
    incomplete = _create_db("bootstrap_incomplete_ci")
    with _db_conn(incomplete) as conn, conn.cursor() as cur:
        cur.execute("CREATE TABLE users (id SERIAL PRIMARY KEY, email VARCHAR(254))")
    failed = _bootstrap(incomplete, success=False)
    assert "schema differs" in failed.stdout or "complete application schema" in failed.stdout
    # 5. Exact previous-head shape, with synthetic financial history. Build it
    # before importing app so import-time create_all exercises the real hazard.
    old = _create_db("bootstrap_previous_head_ci")
    _run(old, """
import sqlalchemy as sa
from models import db
import os
engine=sa.create_engine(os.environ['DATABASE_URL'].replace('postgresql://','postgresql+psycopg2://',1))
meta=sa.MetaData()
for name,table in db.metadata.tables.items():
    if name not in ('paypal_payment_attempt','paypal_payment_event'):
        table.to_metadata(meta)
parent=meta.tables['fiscal_advisory_requests']
for name in ('paypal_quote_generation','paypal_review_hold'):
    parent._columns.remove(parent.c[name])
meta.create_all(engine)
with engine.begin() as c:
    c.execute(sa.text('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
    c.execute(sa.text("INSERT INTO alembic_version VALUES ('v5w6x7y8z9a0')"))
    c.execute(sa.text("INSERT INTO fiscal_advisory_requests (full_name,email,tax_residence_country,tax_year,service_type,case_description,status,amount_paid,currency,payment_provider,paid_at,created_at,updated_at) VALUES ('Synthetic','old@example.invalid','Synthetic',2026,'revision_basica','Synthetic','paid_received',10001,'eur','paypal',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
""")
    _bootstrap(old)
    _assert_version(old)
    with _db_conn(old) as conn, conn.cursor() as cur:
        cur.execute("SELECT amount_paid,currency,payment_provider,status,paypal_quote_generation,paypal_review_hold FROM fiscal_advisory_requests WHERE email='old@example.invalid'")
        assert cur.fetchone()==(10001,'eur','paypal','paid_received',None,True)
        cur.execute("SELECT COUNT(*) FROM paypal_payment_attempt")
        assert cur.fetchone()[0]==0, "Historical attempts must not be invented"
    # 6. A versioned partial schema must not be silently completed on import.
    partial = _create_db("bootstrap_partial_u04_ci")
    _bootstrap(partial)
    with _db_conn(partial) as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE paypal_payment_event CASCADE")
    failed=_bootstrap(partial,success=False)
    with _db_conn(partial) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.paypal_payment_event')")
        assert cur.fetchone()[0] is None, "Import must not repair a partial financial schema"
    # 7. Defaults, CHECK meaning, trigger body/binding and index predicate matter.
    for suffix, statement in (
        ('default',"ALTER TABLE fiscal_advisory_requests ALTER COLUMN paypal_review_hold SET DEFAULT FALSE"),
        ('check',"ALTER TABLE paypal_payment_attempt DROP CONSTRAINT ck_paypal_money; ALTER TABLE paypal_payment_attempt ADD CONSTRAINT ck_paypal_money CHECK (quoted_amount_cents >= 0)"),
        ('trigger',"ALTER TABLE paypal_payment_attempt DISABLE TRIGGER u04_attempt_guard"),
        ('function',"CREATE OR REPLACE FUNCTION u04_attempt_guard_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$"),
        ('index',"DROP INDEX uq_paypal_blocking_advisory; CREATE UNIQUE INDEX uq_paypal_blocking_advisory ON paypal_payment_attempt(advisory_id) WHERE state='UNCERTAIN'"),
    ):
        broken=_create_db('bootstrap_tamper_'+suffix+'_ci')
        _bootstrap(broken)
        with _db_conn(broken) as conn, conn.cursor() as cur: cur.execute(statement)
        failed=_bootstrap(broken,success=False)
        assert 'U04' in failed.stdout, suffix
    print(
        "PostgreSQL bootstrap: fresh schema + seed PASS; repeated existing "
        "database PASS; populated unversioned FAIL-CLOSED PASS; "
        "incomplete schema FAIL-CLOSED PASS; previous head with paid history PASS; "
        "partial financial schema FAIL-CLOSED PASS; five structural tampering checks PASS"
    )


if __name__ == "__main__":
    main()
