"""Create processing_errors table

Revision ID: d1e2f3a4b5c6
Revises: c2d3e4f5a6b7
Create Date: 2026-05-21 00:00:00.000000

Nueva tabla para tracking enriquecido de errores de procesamiento de CSV.
Idempotente: si la tabla ya existe (creada manualmente antes de que Alembic
registrara la revisión), upgrade() la omite y solo crea los índices que falten.
No toca datos existentes.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision      = 'd1e2f3a4b5c6'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on    = None

_TABLE = "processing_errors"

_INDICES = [
    ("ix_processing_errors_created_at",      ["created_at"]),
    ("ix_processing_errors_fingerprint",     ["fingerprint"]),
    ("ix_processing_errors_exchange",        ["exchange"]),
    ("ix_processing_errors_resolved",        ["resolved"]),
    ("ix_processing_errors_auto_email_sent", ["auto_email_sent"]),
]


def upgrade():
    bind = op.get_bind()
    inspector = sa_inspect(bind)

    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id",                 sa.Integer(),    nullable=False),
            sa.Column("created_at",         sa.DateTime(),   nullable=False),
            sa.Column("user_id",            sa.Integer(),    sa.ForeignKey("users.id"), nullable=True),
            sa.Column("email",              sa.String(254),  nullable=True),
            sa.Column("exchange",           sa.String(50),   nullable=True),
            sa.Column("parser",             sa.String(100),  nullable=True),
            sa.Column("stage",              sa.String(50),   nullable=True),
            sa.Column("error_type",         sa.String(100),  nullable=True),
            sa.Column("message_short",      sa.String(500),  nullable=True),
            sa.Column("traceback_short",    sa.Text(),       nullable=True),
            sa.Column("fingerprint",        sa.String(64),   nullable=True),
            sa.Column("csv_filename",       sa.String(255),  nullable=True),
            sa.Column("csv_size",           sa.Integer(),    nullable=True),
            sa.Column("auto_email_sent",    sa.Boolean(),    nullable=False, server_default="0"),
            sa.Column("auto_email_sent_at", sa.DateTime(),   nullable=True),
            sa.Column("email_send_error",   sa.String(500),  nullable=True),
            sa.Column("user_replied",       sa.Boolean(),    nullable=False, server_default="0"),
            sa.Column("resolved",           sa.Boolean(),    nullable=False, server_default="0"),
            sa.Column("resolved_at",        sa.DateTime(),   nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_idx = {
        idx["name"] for idx in inspector.get_indexes(_TABLE)
    } if inspector.has_table(_TABLE) else set()

    for idx_name, columns in _INDICES:
        if idx_name not in existing_idx:
            op.create_index(idx_name, _TABLE, columns)


def downgrade():
    op.drop_index("ix_processing_errors_auto_email_sent", table_name=_TABLE)
    op.drop_index("ix_processing_errors_resolved",        table_name=_TABLE)
    op.drop_index("ix_processing_errors_exchange",        table_name=_TABLE)
    op.drop_index("ix_processing_errors_fingerprint",     table_name=_TABLE)
    op.drop_index("ix_processing_errors_created_at",      table_name=_TABLE)
    op.drop_table(_TABLE)
