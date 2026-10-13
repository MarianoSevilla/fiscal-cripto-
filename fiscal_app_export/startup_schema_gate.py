"""S01-G04 read-only schema gate; called BEFORE Gunicorn, never performs DDL.

A release must receive a separate explicit, authorized migration BEFORE this
gate is used. Startup refuses old/partial/ambiguous schemas rather than
implicitly invoking CREATE TABLE, ALTER TABLE, Alembic stamp or upgrade.
"""
from __future__ import annotations

from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app import app, db


EXPECTED_HEAD = "z9a0b1c2d3e4"
SCHEMA_TABLES = (
    "s01_stripe_checkout_attempts",
    "s01_stripe_event_receipts",
    "s01_stripe_notification_outbox",
)
REQUIRED_COLUMNS = (
    "rafa_fee_cents",
    "commission_cents",
    "commission_rate_bps",
)
REQUIRED_CONSTRAINTS = {
    "s01_stripe_checkout_attempts": {
        "s01_stripe_checkout_attempts_pkey",
        "uq_s01_attempt_advisory",
        "ck_s01_checkout_status",
        "ck_s01_attempt_amount",
        "ck_s01_attempt_currency",
    },
    "s01_stripe_event_receipts": {
        "s01_stripe_event_receipts_pkey",
    },
    "s01_stripe_notification_outbox": {
        "s01_stripe_notification_outbox_pkey",
        "uq_s01_outbox_attempt_kind",
        "ck_s01_outbox_kind",
        "ck_s01_outbox_status",
    },
}
REQUIRED_INDEXES = {"ix_s01_attempt_status", "ix_s01_outbox_status"}


class StartupSchemaError(RuntimeError):
    pass


def _migration_head() -> str:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if tuple(heads) != (EXPECTED_HEAD,):
        raise StartupSchemaError("migration graph is not the approved S01 single head")
    return EXPECTED_HEAD


def verify_schema_readonly() -> None:
    """Inspect only metadata and Alembic revision in a READ ONLY transaction."""
    expected = _migration_head()
    with app.app_context():
        engine = db.engine
        if engine.dialect.name != "postgresql":
            raise StartupSchemaError("PostgreSQL is required for this startup gate")

        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                # The read-only contract is set BEFORE any introspection/query.
                conn.execute(text("SET TRANSACTION READ ONLY"))
                is_readonly = conn.execute(text("SHOW transaction_read_only")).scalar_one()
                if is_readonly != "on":
                    raise StartupSchemaError("database inspection is not read-only")
                inspector = inspect(conn)
                tables = set(inspector.get_table_names(schema="public"))
                model_tables = set(db.metadata.tables)
                required = model_tables | set(SCHEMA_TABLES) | {"alembic_version"}
                if not model_tables or not required.issubset(tables):
                    raise StartupSchemaError("required application tables are absent")

                versions = conn.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
                if versions != [expected]:
                    raise StartupSchemaError("database revision does not match approved S01 head")

                for table, model in db.metadata.tables.items():
                    known_columns = {
                        col["name"] for col in inspector.get_columns(table, schema="public")
                    }
                    if not {c.name for c in model.columns}.issubset(known_columns):
                        raise StartupSchemaError("model columns are missing from PostgreSQL")

                advice_columns = {
                    c["name"] for c in inspector.get_columns("fiscal_advisory_requests", schema="public")
                }
                if not set(REQUIRED_COLUMNS).issubset(advice_columns):
                    raise StartupSchemaError("required advisory breakdown columns missing")

                for table, necessary in REQUIRED_CONSTRAINTS.items():
                    present = {
                        record[0] for record in conn.execute(
                            text(
                                "SELECT conname FROM pg_constraint "
                                "WHERE conrelid = to_regclass(:relation)"
                            ),
                            {"relation": "public." + table},
                        ).all()
                    }
                    if not necessary.issubset(present):
                        raise StartupSchemaError("S01 financial integrity constraints missing")

                indexes = {
                    record[0] for record in conn.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE schemaname = 'public' AND tablename IN "
                            "('s01_stripe_checkout_attempts', 's01_stripe_event_receipts', "
                            "'s01_stripe_notification_outbox')"
                        )
                    ).all()
                }
                if not REQUIRED_INDEXES.issubset(indexes):
                    raise StartupSchemaError("S01 financial integrity indexes missing")
            finally:
                # Never commit even a READ ONLY inspection.
                transaction.rollback()


def main() -> None:
    try:
        verify_schema_readonly()
    except Exception:
        # SQLAlchemy exceptions can contain DSNs, passwords or source data.
        # Keep the startup failure uniformly redacted, never dump tracebacks.
        print("S01 G04 STARTUP: NO-GO (schema/revision verification failed; details protected)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print("S01 G04 STARTUP: PASS (PostgreSQL schema/Alembic checked READ ONLY)",
          flush=True)


if __name__ == "__main__":
    main()
