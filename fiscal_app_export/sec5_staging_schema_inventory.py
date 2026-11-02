"""SEC5 staging read-only catalog inventory: no data rows, no DDL."""
from __future__ import annotations
import sys

from sqlalchemy import inspect, text
from sec5_staging_isolation import validate_envelope
from startup_schema_gate import SCHEMA_TABLES, EXPECTED_HEAD


def main() -> None:
    import os
    try:
        validate_envelope(dict(os.environ))
        # Metadata only: the database schema might be older than the current ORM.
        from app import app, db
        with app.app_context(), db.engine.connect() as conn:
            tx = conn.begin()
            try:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                inspector = inspect(conn)
                tables = set(inspector.get_table_names(schema="public"))
                models = set(db.metadata.tables)
                missing_orm = sorted(models - tables)
                missing_s01 = sorted(set(SCHEMA_TABLES) - tables)
                revisions = []
                if "alembic_version" in tables:
                    revisions = list(conn.execute(text(
                        "SELECT version_num FROM public.alembic_version"
                    )).scalars().all())
                print("SEC5 STAGING SCHEMA INVENTORY: READONLY", flush=True)
                print("ORM_TABLES_REQUIRED:", len(models), flush=True)
                print("PUBLIC_TABLE_COUNT:", len(tables), flush=True)
                print("MISSING_ORM_TABLES:", ",".join(missing_orm) or "(none)", flush=True)
                print("MISSING_S01_TABLES:", ",".join(missing_s01) or "(none)", flush=True)
                print("ALEMBIC_HEAD_EXPECTED:", EXPECTED_HEAD, flush=True)
                print("ALEMBIC_REVISIONS:", ",".join(revisions) or "(absent)", flush=True)
            finally:
                tx.rollback()
    except Exception:
        # Never log DBAPI tracebacks; they can include a DSN or client data.
        print("SEC5 STAGING SCHEMA INVENTORY: NO-GO (details redacted)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
