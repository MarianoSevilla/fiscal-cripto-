"""Add processing_error_id to communication_campaigns

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-06-08 00:00:00.000000

Cambios
-------
  1. ALTER TABLE communication_campaigns ADD COLUMN processing_error_id INTEGER NULL
       FK a processing_errors(id). Nullable — solo presente en campañas individuales
       originadas desde /stats. Idempotente con IF NOT EXISTS.
"""
from alembic import op


revision      = 't3u4v5w6x7y8'
down_revision = 's2t3u4v5w6x7'
branch_labels = None
depends_on    = None


def upgrade():
    op.execute(
        "ALTER TABLE communication_campaigns "
        "ADD COLUMN IF NOT EXISTS processing_error_id INTEGER REFERENCES processing_errors(id) ON DELETE SET NULL"
    )


def downgrade():
    op.execute(
        "ALTER TABLE communication_campaigns "
        "DROP COLUMN IF EXISTS processing_error_id"
    )
