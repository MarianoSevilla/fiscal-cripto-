"""Add csv_context to processing_errors

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-06-28 00:00:00.000000

Cambios
-------
  1. ALTER TABLE processing_errors ADD COLUMN IF NOT EXISTS csv_context TEXT NULL
       Evidencia técnica del CSV capturada en el momento del error (Sprint 1).
       Contiene JSON con: sha256, encoding, separator, headers, n_columns,
       exchange_format_variant (Binance). Nullable — registros históricos no afectados.
       Idempotente con IF NOT EXISTS.
"""
from alembic import op


revision      = 'u4v5w6x7y8z9'
down_revision = 't3u4v5w6x7y8'
branch_labels = None
depends_on    = None


def upgrade():
    op.execute(
        "ALTER TABLE processing_errors "
        "ADD COLUMN IF NOT EXISTS csv_context TEXT"
    )


def downgrade():
    op.execute(
        "ALTER TABLE processing_errors "
        "DROP COLUMN IF EXISTS csv_context"
    )
