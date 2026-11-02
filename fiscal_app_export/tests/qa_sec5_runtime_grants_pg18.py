"""SEC5-PRIV PG18: actual full-schema runtime login, CI ONLY.

No Railway URLs, provider secrets, customer data, or persistent permissions.
Creates a disposable database/LOGIN in GitHub Actions, validates Flask
schema startup and representative real ORM DML as an independent login,
verifies negative privilege boundaries, then drops both.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import subprocess
import sys

import psycopg2
from psycopg2 import errors, sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sec5_priv_runtime_acl import grant_existing_runtime_acl

HOST = "127.0.0.1"
DBNAME = "sec5_runtime_acl_ci"
ROLE = "sec5_runtime_acl_login_ci"
PASS_ADMIN = "ci-only-test-password"
VAULT = "sec5_priv_vault_acl_ci"


def _guard():
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or os.environ.get("FLASK_ENV") != "testing"
        or os.environ.get("SEC5_RUNTIME_ACL_CI_ONLY") != "1"
        or os.environ.get("DATABASE_URL")
        or any(k.startswith("RAILWAY_") for k in os.environ)
        or any(os.environ.get(k) for k in (
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "PAYPAL_CLIENT_SECRET",
            "PAYPAL_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "RESEND_API_KEY",
        ))
    ):
        raise RuntimeError("SEC5 runtime ACL: isolated GitHub CI only")


def _connect(dbname, user, password):
    _guard()
    return psycopg2.connect(
        host=HOST, port=5432, dbname=dbname, user=user,
        password=password, connect_timeout=5,
    )


def _env(user, password):
    result = dict(os.environ)
    result.update({
        "FLASK_ENV": "production",
        "SECRET_KEY": "SEC5-TEST-ONLY-NEVER-PRODUCTION-1234",
        "DATABASE_URL": (
            f"postgresql+psycopg2://{user}:{password}@{HOST}:5432/{DBNAME}"
        ),
        "STRIPE_SECRET_KEY": "", "STRIPE_WEBHOOK_SECRET": "",
        "PAYPAL_CLIENT_SECRET": "", "PAYPAL_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "", "GOOGLE_CLIENT_ID": "",
        "RESEND_API_KEY": "", "FISCAL_ADVISORY_NOTIFY_EMAILS": "",
    })
    result.pop("SEC5_RUNTIME_ACL_CI_ONLY", None)
    return result


def _child(user, password, code):
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT, env=_env(user, password), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=130, check=False,
    )
    if result.returncode:
        # Test-only isolated stdout; avoid logging user/password/DSN.
        raise AssertionError(
            "SEC5 runtime ACL subprocess failed: " +
            result.stdout.replace(password, "[redacted]")
                         .replace(PASS_ADMIN, "[redacted]")[-1700:]
        )
    return result.stdout


def _deny(cur, command):
    cur.execute("SAVEPOINT sec5_acl_denial")
    try:
        try:
            cur.execute(command)
        except errors.InsufficientPrivilege:
            pass
        else:
            raise AssertionError("SEC5 ACL: unexpectedly privileged operation")
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT sec5_acl_denial")
        cur.execute("RELEASE SAVEPOINT sec5_acl_denial")


def _negative_privileges(password, tables):
    with _connect(DBNAME, ROLE, password) as con, con.cursor() as cur:
        cur.execute("""
            SELECT r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb,
                   r.rolreplication,
                   has_schema_privilege('public','CREATE'),
                   has_database_privilege(current_database(),'CREATE'),
                   current_user = session_user
            FROM pg_roles r WHERE r.rolname = current_user
        """)
        assert cur.fetchone() == (False, False, False, False, False,
                                  False, False, True)
        cur.execute("SELECT version_num FROM public.alembic_version")
        assert cur.fetchone() == ("z9a0b1c2d3e4",)
        _deny(cur, "DELETE FROM public.alembic_version")
        _deny(cur, "TRUNCATE TABLE public.contactos")
        _deny(cur, "CREATE TABLE public.sec5_unauthorized_ci (id integer)")
        _deny(cur, "ALTER TABLE public.users ADD COLUMN sec5_unauthorized_ci integer")
        _deny(cur, "SELECT secret FROM sec5_priv_vault_acl_ci.blocked_evidence")
        _deny(cur, "SET ROLE postgres")
        cur.execute("""
            SELECT c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p')
              AND has_table_privilege(current_user, c.oid, 'INSERT')
        """)
        assert {x[0] for x in cur.fetchall()} == tables, (
            "Unexpected DML privilege on a non-ORM table"
        )


def main():
    _guard()
    from app import db
    tables = set(db.metadata.tables)
    assert len(tables) == 17 and "alembic_version" not in tables
    password = secrets.token_hex(24)

    admin = _connect("postgres", "postgres", PASS_ADMIN)
    admin.autocommit = True
    created_db = False
    created_role = False
    try:
        with admin.cursor() as cur:
            cur.execute("SELECT current_setting('server_version_num')::integer / 10000")
            assert cur.fetchone()[0] == 18
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DBNAME)))
            created_db = True
            cur.execute(sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD {}"
            ).format(sql.Identifier(ROLE), sql.Literal(password)))
            created_role = True

        _child("postgres", PASS_ADMIN,
               "from bootstrap_db import main; main()")
        _child("postgres", PASS_ADMIN,
               "from startup_schema_gate import main; main()")

        with _connect(DBNAME, "postgres", PASS_ADMIN) as con:
            with con.cursor() as cur:
                # A superuser must be rejected BEFORE any role GRANT.
                try:
                    grant_existing_runtime_acl(
                        cur, login="postgres", model_tables=tables
                    )
                except ValueError as exc:
                    assert "safe LOGIN" in str(exc)
                else:
                    raise AssertionError("Privileged target passed ACL preflight")
                cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(VAULT)))
                cur.execute(sql.SQL(
                    "CREATE TABLE {}.blocked_evidence (id integer, secret text)"
                ).format(sql.Identifier(VAULT)))
                cur.execute(sql.SQL(
                    "INSERT INTO {}.blocked_evidence VALUES (1,'synthetic-only')"
                ).format(sql.Identifier(VAULT)))
                summary = grant_existing_runtime_acl(
                    cur, login=ROLE, model_tables=tables
                )
        assert summary["orm_tables"] == 17 and summary["alembic_readonly"]
        assert summary["future_grants"] is False

        # Actual web startup on the least-privileged login.
        startup = _child(ROLE, password,
                         "from startup_schema_gate import main; main()")
        assert "STARTUP: PASS" in startup

        # Representative ORM inserts, updates, deletes, joins, FK enforcement
        # and sequence-backed primary keys under the restricted login.
        smoke = r'''
from app import app, db
from models import User, FifoReport, Contacto, FiscalAdvisoryRequest
with app.app_context():
    engine = db.engine
    with engine.connect() as con:
        assert con.exec_driver_sql("SELECT current_user = session_user").scalar()
    user = User(email="sec5-ci-user@example.invalid", full_name="Synthetic user")
    db.session.add(user)
    db.session.commit()
    assert user.id > 0
    report = FifoReport(user_id=user.id, exchange="bitvavo", fiscal_year=2025)
    case = FiscalAdvisoryRequest(
        user_id=user.id, full_name="Synthetic taxpayer",
        email="sec5-ci-user@example.invalid", tax_residence_country="España",
        tax_year=2025, service_type="presupuesto_personalizado",
        case_description="Synthetic case: no real services")
    contact = Contacto(nombre="Synthetic", email="sec5-ci-user@example.invalid",
        tipo_consulta="general", mensaje="CI-only message")
    db.session.add_all([report, case, contact])
    db.session.commit()
    assert report.id > 0 and case.id > 0 and contact.id > 0
    assert FifoReport.query.filter_by(user_id=user.id).count() == 1
    assert FiscalAdvisoryRequest.query.filter_by(user_id=user.id).count() == 1
    report.status = "failed"
    case.status = "under_review"
    db.session.delete(contact)
    db.session.commit()
    assert FifoReport.query.get(report.id).status == "failed"
    assert FiscalAdvisoryRequest.query.get(case.id).status == "under_review"
    assert Contacto.query.filter_by(email="sec5-ci-user@example.invalid").count() == 0
    guest = app.test_client()
    assert guest.get("/healthz").status_code == 200
    assert guest.get("/api/me").status_code == 200
    db.session.remove()
'''
        _child(ROLE, password, smoke)
        _negative_privileges(password, tables)
        print("SEC5_RUNTIME_ACL_PG18: PASS (17 ORM; full-schema startup; "
              "synthetic user/FIFO/advisory/contact DML; deny DDL/vault; "
              "no providers; no Railway)")
    finally:
        with admin.cursor() as cur:
            if created_db:
                cur.execute(sql.SQL(
                    "DROP DATABASE IF EXISTS {} WITH (FORCE)"
                ).format(sql.Identifier(DBNAME)))
            if created_role:
                cur.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(ROLE)))
        admin.close()


if __name__ == "__main__":
    main()
