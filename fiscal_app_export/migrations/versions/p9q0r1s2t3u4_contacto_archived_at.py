"""Añade columna archived_at a contactos (soft-delete)

Revision ID: p9q0r1s2t3u4
Revises: o8p9q0r1s2t3
Create Date: 2026-06-01 00:00:00.000000

Cambio
------
  ALTER TABLE contactos ADD COLUMN archived_at TIMESTAMP NULL
  La columna es nullable y no requiere backfill: registros existentes quedan
  con NULL (= activos). Operación segura e idempotente en PostgreSQL.
"""

from alembic import op
import sqlalchemy as sa

revision      = "p9q0r1s2t3u4"
down_revision = "o8p9q0r1s2t3"
branch_labels = None
depends_on    = None


def upgrade():
    with op.batch_alter_table("contactos") as batch_op:
        batch_op.add_column(
            sa.Column("archived_at", sa.DateTime(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("contactos") as batch_op:
        batch_op.drop_column("archived_at")
