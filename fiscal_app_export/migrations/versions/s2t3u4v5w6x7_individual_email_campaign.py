"""Add individual_email to communication_campaigns

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-06-08 00:00:00.000000

Cambios
-------
  1. ALTER TABLE communication_campaigns ADD COLUMN individual_email VARCHAR(254) NULL
       Idempotente con IF NOT EXISTS.
       Usada cuando recipient_segment='individual' para enviar a un único destinatario.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 's2t3u4v5w6x7'
down_revision = 'r1s2t3u4v5w6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE communication_campaigns "
        "ADD COLUMN IF NOT EXISTS individual_email VARCHAR(254)"
    )


def downgrade():
    # Postgres: DROP COLUMN IF EXISTS is safe
    op.execute(
        "ALTER TABLE communication_campaigns "
        "DROP COLUMN IF EXISTS individual_email"
    )
