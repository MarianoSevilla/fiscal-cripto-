"""add nif to users

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-05-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade():
    if not _column_exists("users", "nif"):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(sa.Column("nif", sa.String(length=20), nullable=True))


def downgrade():
    if _column_exists("users", "nif"):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("nif")
