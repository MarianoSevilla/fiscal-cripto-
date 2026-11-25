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


EXPECTED_HEAD = "a2b3c4d5e6f7"
SCHEMA_TABLES = (
    "s01_stripe_checkout_attempts",
    "s01_stripe_event_receipts",
    "s01_stripe_notification_outbox",
    "credit_wallets",
    "credit_ledger_entries",
    "credit_purchases",
    "credit_stripe_event_receipts",
    "credit_analyses",
    "credit_report_artifacts",
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
    "credit_wallets": {
        "credit_wallets_pkey", "ck_credit_wallet_available",
        "ck_credit_wallet_reserved",
    },
    "credit_ledger_entries": {
        "credit_ledger_entries_pkey", "ck_credit_ledger_nonzero",
        "credit_ledger_entries_idempotency_key_key",
    },
    "credit_purchases": {
        "credit_purchases_pkey", "credit_purchases_idempotency_key_key",
        "credit_purchases_checkout_session_id_key", "credit_purchases_stripe_event_id_key",
        "ck_credit_purchase_status", "ck_credit_purchase_amount_credits",
        "ck_credit_purchase_currency",
    },
    "credit_stripe_event_receipts": {"credit_stripe_event_receipts_pkey"},
    "credit_analyses": {
        "credit_analyses_pkey", "ck_credit_analysis_status",
        "ck_credit_analysis_amounts", "uq_credit_analysis_user_key",
        "uq_credit_analysis_free_correction",
    },
    "credit_report_artifacts": {"credit_report_artifacts_pkey"},
}
REQUIRED_INDEXES = {
    "ix_s01_attempt_status", "ix_s01_outbox_status",
    "ix_credit_ledger_user_created", "ix_credit_purchases_user_id",
    "ix_credit_analysis_user_created", "ix_credit_report_artifacts_expires_at",
}


class StartupSchemaError(RuntimeError):
    pass


def _migration_head() -> str:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if tuple(heads) != (EXPECTED_HEAD,):
        raise StartupSchemaError("migration graph is not the approved application single head")
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
                    raise StartupSchemaError("database revision does not match approved application head")

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
                            "'s01_stripe_notification_outbox', 'credit_ledger_entries', "
                            "'credit_purchases', 'credit_analyses', 'credit_report_artifacts')"
                        )
                    ).all()
                }
                if not REQUIRED_INDEXES.issubset(indexes):
                    raise StartupSchemaError("S01 financial integrity indexes missing")
            finally:
                # Never commit even a READ ONLY inspection.
                transaction.rollback()


# Explicit fixed taxonomy; never print arbitrary exceptions from SQLAlchemy
# because DBAPI errors can contain connection strings and client data.
_SAFE_FAILURE_CODES = {
    "migration graph is not the approved application single head": "GRAPH",
    "PostgreSQL is required for this startup gate": "DATABASE",
    "database inspection is not read-only": "READONLY",
    "required application tables are absent": "TABLES",
    "database revision does not match approved application head": "REVISION",
    "model columns are missing from PostgreSQL": "COLUMNS",
    "required advisory breakdown columns missing": "ADVISORY_COLUMNS",
    "S01 financial integrity constraints missing": "CONSTRAINTS",
    "S01 financial integrity indexes missing": "INDEXES",
}


def main() -> None:
    try:
        verify_schema_readonly()
    except StartupSchemaError as exc:
        code = _SAFE_FAILURE_CODES.get(str(exc), "CHECK")
        print("S01 G04 STARTUP: NO-GO (" + code + "; details protected)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        # SQLAlchemy exceptions can contain DSNs, passwords or source data.
        # Keep failures uniformly redacted, never dump tracebacks.
        print("S01 G04 STARTUP: NO-GO (INTERNAL; details protected)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print("S01 G04 STARTUP: PASS (PostgreSQL schema/Alembic checked READ ONLY)",
          flush=True)


if __name__ == "__main__":
    main()
