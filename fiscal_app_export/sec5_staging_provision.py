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
    # Explicit mode is consumed only by the original STG-LOCK-001 guard.
    env["SEC5_STAGING_DB_MODE"] = (
        "RUNTIME" if make_url(database_url).username == ROLE else "BOOTSTRAP"
    )
    # External provider credentials are already checked as empty by the gate.
    # A child failure can contain DB credentials in its normal traceback.
    # The only emitted diagnostics are an exception CLASS, optional SQLSTATE,
    # and source module/line: never error messages, DSNs or stdout.
    wrapper = (
        "import sys, traceback\n"
        "try:\n"
        "    exec(" + repr(command) + ")\n"
        "except BaseException as exc:\n"
        "    frames = traceback.extract_tb(exc.__traceback__)\n"
        "    last = frames[-1] if frames else None\n"
        "    origin = getattr(exc, 'orig', None)\n"
        "    code = getattr(origin, 'pgcode', None) or 'none'\n"
        "    where = (last.filename.rsplit('/', 1)[-1] if last else 'none')\n"
        "    line = last.lineno if last else 0\n"
        "    print('SEC5 CHILD SAFE FAILURE: class=' + type(exc).__name__ + "
        "' cause=' + (type(exc.__cause__).__name__ if exc.__cause__ else 'none') "
        "+ ' sqlstate=' + str(code) + ' at=' + where + ':' + str(line), flush=True)\n"
        "    sys.exit(1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", wrapper],
        cwd=Path(__file__).resolve().parent,
        env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=140, check=False, text=True,
    )
    if result.returncode:
        for line in result.stdout.splitlines():
            if line.startswith("SEC5 CHILD SAFE FAILURE:"):
                print(line, flush=True)
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
    print("SEC5 STAGING PROVISION PHASE: ENVELOPE_OK", flush=True)
    password = env[PW_VAR]
    old_url = make_url(env["DATABASE_URL"])
    # SQLAlchemy str(URL) REDACTS passwords as ***. Explicit rendering is
    # mandatory for internal subprocess DSNs; never print either string.
    admin_new_url = old_url.set(database=DBNAME).render_as_string(hide_password=False)
    runtime_url = old_url.set(
        database=DBNAME, username=ROLE, password=password
    ).render_as_string(hide_password=False)
    # DBAPI connection to the *already isolated* staging Postgres only.
    import psycopg2
    from app import app, db
    with app.app_context():
        admin = psycopg2.connect(
            host=old_url.host, port=old_url.port or 5432,
            dbname=old_url.database, user=old_url.username,
            password=old_url.password, connect_timeout=8,
        )
        print("SEC5 STAGING PROVISION PHASE: ADMIN_CONNECTED", flush=True)
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
                print("SEC5 STAGING PROVISION PHASE: TARGETS_ABSENT", flush=True)
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DBNAME)))
                created_db = True
                print("SEC5 STAGING PROVISION PHASE: DATABASE_CREATED", flush=True)
                cur.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION "
                    "NOINHERIT PASSWORD {}"
                ).format(sql.Identifier(ROLE), sql.Literal(password)))
                created_role = True
                print("SEC5 STAGING PROVISION PHASE: ROLE_CREATED", flush=True)

            # Fresh, standalone database: only the explicit bootstrap may
            # build/migrate the schema. Never modify the old staging database.
            _run_isolated(
                "from bootstrap_db import main; main()", admin_new_url, env
            )
            print("SEC5 STAGING PROVISION PHASE: BOOTSTRAP_PASS", flush=True)
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

            print("SEC5 STAGING PROVISION PHASE: GRANTS_PASS", flush=True)
            _limited_check(runtime_url)
            print("SEC5 STAGING PROVISION PHASE: LIMITED_LOGIN_PASS", flush=True)
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
            print("SEC5 STAGING PROVISION PHASE: CLEANUP_DONE", flush=True)
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
