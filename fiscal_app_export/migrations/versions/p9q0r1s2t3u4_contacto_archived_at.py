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
    # IF NOT EXISTS: idempotente si la columna ya fue creada manualmente.
    op.execute("ALTER TABLE contactos ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")


def downgrade():
    op.execute("ALTER TABLE contactos DROP COLUMN IF EXISTS archived_at")
