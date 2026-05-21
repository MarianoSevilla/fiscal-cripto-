"""Create processing_errors table

Revision ID: d1e2f3a4b5c6
Revises: c2d3e4f5a6b7
Create Date: 2026-05-21 00:00:00.000000

Nueva tabla para tracking enriquecido de errores de procesamiento de CSV.
No toca tablas existentes. Todas las columnas de negocio son nullable.
Booleanos con server_default para compatibilidad con SQLite (Railway).
"""
from alembic import op
import sqlalchemy as sa


revision      = 'd1e2f3a4b5c6'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        "processing_errors",
        sa.Column("id",                 sa.Integer(),     nullable=False),
        sa.Column("created_at",         sa.DateTime(),    nullable=False),
        sa.Column("user_id",            sa.Integer(),     sa.ForeignKey("users.id"), nullable=True),
        sa.Column("email",              sa.String(254),   nullable=True),
        sa.Column("exchange",           sa.String(50),    nullable=True),
        sa.Column("parser",             sa.String(100),   nullable=True),
        sa.Column("stage",              sa.String(50),    nullable=True),
        sa.Column("error_type",         sa.String(100),   nullable=True),
        sa.Column("message_short",      sa.String(500),   nullable=True),
        sa.Column("traceback_short",    sa.Text(),        nullable=True),
        sa.Column("fingerprint",        sa.String(64),    nullable=True),
        sa.Column("csv_filename",       sa.String(255),   nullable=True),
        sa.Column("csv_size",           sa.Integer(),     nullable=True),
        sa.Column("auto_email_sent",    sa.Boolean(),     nullable=False, server_default="0"),
        sa.Column("auto_email_sent_at", sa.DateTime(),    nullable=True),
        sa.Column("email_send_error",   sa.String(500),   nullable=True),
        sa.Column("user_replied",       sa.Boolean(),     nullable=False, server_default="0"),
        sa.Column("resolved",           sa.Boolean(),     nullable=False, server_default="0"),
        sa.Column("resolved_at",        sa.DateTime(),    nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processing_errors_created_at",      "processing_errors", ["created_at"])
    op.create_index("ix_processing_errors_fingerprint",     "processing_errors", ["fingerprint"])
    op.create_index("ix_processing_errors_exchange",        "processing_errors", ["exchange"])
    op.create_index("ix_processing_errors_resolved",        "processing_errors", ["resolved"])
    op.create_index("ix_processing_errors_auto_email_sent", "processing_errors", ["auto_email_sent"])


def downgrade():
    op.drop_index("ix_processing_errors_auto_email_sent", table_name="processing_errors")
    op.drop_index("ix_processing_errors_resolved",        table_name="processing_errors")
    op.drop_index("ix_processing_errors_exchange",        table_name="processing_errors")
    op.drop_index("ix_processing_errors_fingerprint",     table_name="processing_errors")
    op.drop_index("ix_processing_errors_created_at",      table_name="processing_errors")
    op.drop_table("processing_errors")
