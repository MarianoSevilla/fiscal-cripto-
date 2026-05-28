"""add error_category and error_code for structured error taxonomy

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
Create Date: 2026-05-28 00:00:00.000000

Adds:
  - fifo_reports.error_category     (String 50, nullable)
      Values: None (éxito) | "parser_error" | "unsupported_format" | "user_error"
  - processing_errors.error_category (String 50, nullable)
  - processing_errors.error_code     (String 50, nullable)
      e.g. "futures", "staking", "earn", "copy_trading", "wrong_file", "xlsx_corrupt"

Rationale:
  Separates consciously unsupported formats (futures, staking, etc.) from
  real parser bugs so /stats no longer marks MEXC as "problematic" due to
  users uploading futures exports.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision      = 'k4l5m6n7o8p9'
down_revision = 'j3k4l5m6n7o8'
branch_labels = None
depends_on    = None


def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)

    # ── fifo_reports ──────────────────────────────────────────────────────────
    fifo_cols = {c["name"] for c in insp.get_columns("fifo_reports")}

    if "error_category" not in fifo_cols:
        op.add_column(
            "fifo_reports",
            sa.Column("error_category", sa.String(50), nullable=True),
        )

    # ── processing_errors ─────────────────────────────────────────────────────
    # Table may not exist on very old instances; guard via Inspector.
    existing_tables = insp.get_table_names()
    if "processing_errors" in existing_tables:
        proc_cols = {c["name"] for c in insp.get_columns("processing_errors")}

        if "error_category" not in proc_cols:
            op.add_column(
                "processing_errors",
                sa.Column("error_category", sa.String(50), nullable=True),
            )
        if "error_code" not in proc_cols:
            op.add_column(
                "processing_errors",
                sa.Column("error_code", sa.String(50), nullable=True),
            )


def downgrade():
    op.drop_column("fifo_reports", "error_category")
    try:
        op.drop_column("processing_errors", "error_code")
        op.drop_column("processing_errors", "error_category")
    except Exception:
        pass
