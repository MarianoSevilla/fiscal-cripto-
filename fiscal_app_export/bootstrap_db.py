"""Explicit (non-web) database initialization and Alembic upgrade.

Flask import is DDL-free. Existing, versioned databases are upgraded only by
this separately authorized entrypoint. Only a truly empty PostgreSQL database
may be initialized from the current SQLAlchemy model schema; no partial,
populated or ambiguous unversioned database may be silently repaired/stamped.

NEVER call this program from the web Procfile. A production migration requires
a separate approved rollout and restoration/rollback plan.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from flask_migrate import stamp, upgrade

# Import Flask app only after its import path became DDL-free.
from app import app, db

# The next revision (n7o8p9q0r1s2) seeds the Bitcoin dossier and subsequent
# migrations update that seed. Do not stamp straight to head.
FRESH_SCHEMA_BASELINE = "m6n7o8p9q0r1"


def _revision(engine) -> str | None:
    inspector = inspect(engine)
    if not inspector.has_table("alembic_version"):
        return None
    with engine.connect() as connection:
        revisions = list(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
    if not revisions:
        return None
    if len(revisions) != 1:
        raise RuntimeError("Unexpected Alembic revision state; refusing bootstrap")
    return revisions[0]


def _assert_pristine_current_schema(engine) -> None:
    """Do not silently stamp legacy, incomplete, or populated databases."""
    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())
    model_tables = set(db.metadata.tables)

    if not model_tables or not model_tables.issubset(live_tables):
        missing = model_tables - live_tables
        raise RuntimeError(
            "Database is not a complete application schema; bootstrap refused. "
            f"Missing model tables: {sorted(missing)}"
        )

    for table_name, model in db.metadata.tables.items():
        live_columns = {c["name"] for c in inspector.get_columns(table_name)}
        required_columns = {c.name for c in model.columns}
        if not required_columns.issubset(live_columns):
            raise RuntimeError(
                "Database schema differs from current application models; "
                f"bootstrap refused for table {table_name!r}"
            )

    # Scan ALL non-Alembic tables, including those created using raw SQL.
    # No data-bearing database is ever auto-stamped.
    preparer = engine.dialect.identifier_preparer
    with engine.connect() as connection:
        for table_name in sorted(live_tables - {"alembic_version"}):
            escaped_table = preparer.quote_identifier(table_name)
            populated = connection.execute(
                text(f"SELECT 1 FROM {escaped_table} LIMIT 1")
            ).first()
            if populated is not None:
                raise RuntimeError(
                    "Database already contains records; refusing to stamp "
                    "unversioned schema. Manual migration review required."
                )


def main() -> None:
    with app.app_context():
        if db.engine.dialect.name != "postgresql":
            # SQLite/local development follows the original Alembic flow.
            upgrade()
            return

        current = _revision(db.engine)
        if current is not None:
            upgrade()
            print("DB bootstrap: existing Alembic history upgraded", flush=True)
            return

        tables = set(inspect(db.engine).get_table_names())
        if not tables:
            # Creating a new schema is permitted ONLY inside this explicit
            # command AFTER verifying there are absolutely no tables.
            # Gunicorn/application imports and the Procfile never reach here.
            db.create_all()
            print("DB bootstrap: pristine empty PostgreSQL created explicitly", flush=True)
        # A populated, partial or unversioned legacy schema is never repaired
        # just because the ORM knows how to add a missing table.
        _assert_pristine_current_schema(db.engine)
        print(
            "DB bootstrap: empty current-model PostgreSQL schema verified; "
            "stamping legacy baseline before seed/data migrations",
            flush=True,
        )
        stamp(revision=FRESH_SCHEMA_BASELINE)
        upgrade()
        print("DB bootstrap: fresh schema at Alembic head", flush=True)


if __name__ == "__main__":
    main()
