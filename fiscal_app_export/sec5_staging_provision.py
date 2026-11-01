"""SEC5-PRIV — one-shot STAGING ONLY isolated database + limited Flask role.

Requires explicit staging Railway deployment with approval and a strong
short-lived password supplied as a staging-only Railway environment variable.
Never run in production, from app import, Procfile or scheduled automation.
No customer tables read. The existing staging database remains untouched.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

from psycopg2 import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from sec5_staging_isolation import validate_envelope
from sec5_priv_runtime_acl import grant_existing_runtime_acl

DBNAME = "sec5_priv_stage_20261101"
ROLE = "sec5_runtime_stage"
PW_VAR = "SEC5_STAGING_PROVISION_PASSWORD"
OPT_VAR = "SEC5_STAGING_PROVISION"
OPT_VALUE = "EXPLICIT_ONCE"


def validate_provision_envelope(env: dict[str, str]) -> None:
    validate_envelope(env)
    if env.get(OPT_VAR) != OPT_VALUE:
        raise ValueError("One-shot provisioning not explicitly enabled")
    password = env.get(PW_VAR, "")
    if len(password) < 48 or not re.fullmatch(r"[A-Za-z0-9_-]+", password):
        raise ValueError("Strong URL-safe one-shot password required")


def _run_isolated(command: str, database_url: str, original: dict[str, str]) -> None:
    env = dict(original)
    env["DATABASE_URL"] = database_url
    # External provider credentials are already checked as empty by the gate.
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=Path(__file__).resolve().parent,
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=140, check=False,
    )
    if result.returncode:
        raise RuntimeError("SEC5 staging bootstrap or schema gate rejected")


def _limited_check(url: str) -> None:
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                row = conn.exec_driver_sql("""
                    SELECT r.rolsuper, r.rolbypassrls, r.rolcreaterole,
                           r.rolcreatedb, r.rolreplication,
                           has_schema_privilege('public', 'CREATE'),
                           has_database_privilege(current_database(), 'CREATE'),
                           current_user = session_user
                    FROM pg_roles r WHERE r.rolname = current_user
                """).one()
                if row != (False, False, False, False, False, False, False, True):
                    raise RuntimeError("Unsafe staging runtime privilege")
                conn.exec_driver_sql("SELECT version_num FROM public.alembic_version")
            finally:
                tx.rollback()
    finally:
        engine.dispose()


def provision() -> None:
    env = dict(os.environ)
    validate_provision_envelope(env)
    password = env[PW_VAR]
    old_url = make_url(env["DATABASE_URL"])
    admin_new_url = str(old_url.set(database=DBNAME))
    runtime_url = str(old_url.set(
        database=DBNAME, username=ROLE, password=password
    ))
    # DBAPI connection to the *already isolated* staging Postgres only.
    from app import app, db
    with app.app_context():
        admin = db.engine.raw_connection()
        created_db = False
        created_role = False
        try:
            admin.autocommit = True
            with admin.cursor() as cur:
                cur.execute("""
                    SELECT rolsuper FROM pg_roles WHERE rolname = current_user
                """)
                if cur.fetchone() != (True,):
                    raise RuntimeError("Staging administrative connection required")
                cur.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (DBNAME,)
                )
                if cur.fetchone() is not None:
                    raise RuntimeError("Staging isolated DB already exists; fail closed")
                cur.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,)
                )
                if cur.fetchone() is not None:
                    raise RuntimeError("Staging runtime role already exists; fail closed")
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DBNAME)))
                created_db = True
                cur.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION "
                    "NOINHERIT PASSWORD {}"
                ).format(sql.Identifier(ROLE), sql.Literal(password)))
                created_role = True

            # Fresh, standalone database: only the explicit bootstrap may
            # build/migrate the schema. Never modify the old staging database.
            _run_isolated(
                "from bootstrap_db import main; main()", admin_new_url, env
            )
            engine = create_engine(admin_new_url)
            try:
                dbapi = engine.raw_connection()
                try:
                    with dbapi.cursor() as cur:
                        result = grant_existing_runtime_acl(
                            cur, login=ROLE, model_tables=set(db.metadata.tables)
                        )
                        if result["orm_tables"] != 17:
                            raise RuntimeError("Unexpected ORM table inventory")
                    dbapi.commit()
                finally:
                    dbapi.close()
            finally:
                engine.dispose()

            _limited_check(runtime_url)
            _run_isolated(
                "from startup_schema_gate import main; main()", runtime_url, env
            )
            print(
                "SEC5 STAGING ROLE: PASS "
                "(fresh isolated staging database; full Alembic bootstrap; "
                "17-table limited login; startup verified; old staging DB unchanged)",
                flush=True,
            )
        except BaseException:
            # Only discard objects actually created in THIS single execution.
            # A collision with any pre-existing database/role is not modified.
            with admin.cursor() as cur:
                if created_db:
                    cur.execute(sql.SQL(
                        "DROP DATABASE IF EXISTS {} WITH (FORCE)"
                    ).format(sql.Identifier(DBNAME)))
                if created_role:
                    cur.execute(sql.SQL(
                        "DROP ROLE IF EXISTS {}"
                    ).format(sql.Identifier(ROLE)))
            raise
        finally:
            admin.close()


def main() -> None:
    try:
        provision()
    except Exception:
        # Never print DBAPI errors or DSNs; they can contain passwords.
        print("SEC5 STAGING ROLE: NO-GO (details redacted)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
