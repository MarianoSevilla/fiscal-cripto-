"""add password_reset fields to users

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-05-26 00:00:00.000000

Adds:
  - users.password_reset_token_hash  (String 64, nullable)
  - users.password_reset_expires_at  (DateTime, nullable)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision      = 'j3k4l5m6n7o8'
down_revision = 'i2j3k4l5m6n7'
branch_labels = None
depends_on    = None


def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    cols = {c["name"] for c in insp.get_columns("users")}

    if "password_reset_token_hash" not in cols:
        op.add_column(
            "users",
            sa.Column("password_reset_token_hash", sa.String(64), nullable=True),
        )
    if "password_reset_expires_at" not in cols:
        op.add_column(
            "users",
            sa.Column("password_reset_expires_at", sa.DateTime, nullable=True),
        )


def downgrade():
    op.drop_column("users", "password_reset_expires_at")
    op.drop_column("users", "password_reset_token_hash")
