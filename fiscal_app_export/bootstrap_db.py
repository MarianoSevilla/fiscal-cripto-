"""Safely initialize a new PostgreSQL database, then run Alembic.

Historical migrations begin by ALTERing pre-existing tables; importing app.py
already calls db.create_all() with the CURRENT model schema. Running historical
ALTERs on that newly created schema fails with DuplicateColumn.

Only on a fully empty, current-model PostgreSQL schema with no migration
revision do we stamp the last legacy schema revision and run the remaining,
audited idempotent/data migrations. Existing, versioned databases always
follow the original Flask CLI database upgrade path. Ambiguous databases fail shut.

This is an explicit process entrypoint, NOT an app-import side effect.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from flask_migrate import stamp, upgrade

# Keep app import semantics identical to the prior Flask DB upgrade CLI.
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
            from paypal_schema import verify_structure
            with db.engine.begin() as connection:
                verify_structure(connection)
            print("DB bootstrap: existing Alembic history upgraded", flush=True)
            return

        _assert_pristine_current_schema(db.engine)
        print(
            "DB bootstrap: empty current-model PostgreSQL schema verified; "
            "stamping legacy baseline before seed/data migrations",
            flush=True,
        )
        stamp(revision=FRESH_SCHEMA_BASELINE)
        upgrade()
        from paypal_schema import verify_structure
        with db.engine.begin() as connection:
            verify_structure(connection)
        print("DB bootstrap: fresh schema at Alembic head", flush=True)


if __name__ == "__main__":
    main()
