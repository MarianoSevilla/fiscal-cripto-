"""PostgreSQL 18 CI only: role metadata contract using REAL limited login."""
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sec5_priv_role_preflight import inspect_runtime_role

HOST = "127.0.0.1"
ROLE = "sec5_priv_preflight_ci_login"
PASSWORD = "ci-only-sec5-role-audit-password"


def main():
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("FLASK_ENV") != "testing"
        or os.environ.get("SEC5_PRIV_PREFLIGHT_PG18_ONLY") != "1"
    ):
        raise RuntimeError("SEC5 role preflight: CI-only gate closed")

    admin = psycopg2.connect(
        host=HOST, port=5432, user="postgres",
        password="ci-only-test-password", dbname="postgres",
        connect_timeout=5,
    )
    admin.autocommit = True
    created = False
    try:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT current_database(), current_user, "
                "current_setting('server_version_num')::integer / 10000"
            )
            assert cur.fetchone() == ("postgres", "postgres", 18)
            cur.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(ROLE), sql.Literal(PASSWORD)
                )
            )
            created = True

        super_engine = create_engine(
            "postgresql+psycopg2://postgres:ci-only-test-password@127.0.0.1:5432/postgres"
        )
        limited_engine = create_engine(
            f"postgresql+psycopg2://{ROLE}:{PASSWORD}@127.0.0.1:5432/postgres"
        )
        try:
            super_result = inspect_runtime_role(super_engine)
            limited_result = inspect_runtime_role(limited_engine)
            assert super_result["status"] == "NEEDS_SEPARATION"
            assert "superuser" in super_result["risk_flags"]
            assert limited_result["status"] == "CANDIDATE_ONLY"
            assert not limited_result["risk_flags"]
            assert not limited_result["vault_isolation_proven"]
            assert not limited_result["production_authorized"]
        finally:
            limited_engine.dispose()
            super_engine.dispose()

        print("SEC5_PRIV_ROLE_PREFLIGHT_PG18: PASS")
    finally:
        if created:
            with admin.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(ROLE))
                )
        admin.close()


if __name__ == "__main__":
    main()
