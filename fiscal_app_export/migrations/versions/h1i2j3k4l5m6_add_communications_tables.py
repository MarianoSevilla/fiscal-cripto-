"""add communications tables and user unsubscribe fields

Revision ID: h1i2j3k4l5m6
Revises: f4b5c6d7e8a9
Create Date: 2026-05-25 00:00:00.000000

Adds:
  - users.comms_opted_out        (Boolean, default false)
  - users.comms_unsubscribe_token (String 64, unique, nullable)
  - communication_campaigns table
  - communication_deliveries table
  - Backfills unsubscribe tokens for all existing users
"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = 'h1i2j3k4l5m6'
down_revision = 'f4b5c6d7e8a9'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)

    existing_cols = {c["name"] for c in insp.get_columns("users")}

    if "comms_opted_out" not in existing_cols:
        op.add_column(
            "users",
            sa.Column("comms_opted_out", sa.Boolean(), nullable=False, server_default="false"),
        )

    if "comms_unsubscribe_token" not in existing_cols:
        op.add_column(
            "users",
            sa.Column("comms_unsubscribe_token", sa.String(64), nullable=True),
        )
        try:
            op.create_unique_constraint(
                "uq_users_comms_unsubscribe_token",
                "users",
                ["comms_unsubscribe_token"],
            )
        except Exception:
            pass
        try:
            op.create_index(
                "ix_users_comms_unsubscribe_token",
                "users",
                ["comms_unsubscribe_token"],
                unique=True,
            )
        except Exception:
            pass

        # Backfill unique tokens for every existing user
        rows = conn.execute(sa.text("SELECT id FROM users")).fetchall()
        for row in rows:
            token = uuid.uuid4().hex
            conn.execute(
                sa.text(
                    "UPDATE users SET comms_unsubscribe_token = :token WHERE id = :id"
                ),
                {"token": token, "id": row[0]},
            )

    existing_tables = insp.get_table_names()

    if "communication_campaigns" not in existing_tables:
        op.create_table(
            "communication_campaigns",
            sa.Column("id",               sa.Integer(),     nullable=False),
            sa.Column("subject",          sa.String(500),   nullable=False),
            sa.Column("body",             sa.Text(),         nullable=False),
            sa.Column("preview_text",     sa.String(200),   nullable=True),
            sa.Column("status",           sa.String(20),    nullable=False, server_default="draft"),
            sa.Column("created_by_id",    sa.Integer(),     nullable=True),
            sa.Column("created_at",       sa.DateTime(),    nullable=False),
            sa.Column("sent_at",          sa.DateTime(),    nullable=True),
            sa.Column("recipients_count", sa.Integer(),     nullable=False, server_default="0"),
            sa.Column("error_message",    sa.Text(),         nullable=True),
            sa.Column("idempotency_key",  sa.String(64),    nullable=True),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_comms_campaign_idempotency_key"),
        )
        op.create_index(
            "ix_communication_campaigns_status",
            "communication_campaigns",
            ["status"],
        )
        op.create_index(
            "ix_communication_campaigns_created_at",
            "communication_campaigns",
            ["created_at"],
        )

    if "communication_deliveries" not in existing_tables:
        op.create_table(
            "communication_deliveries",
            sa.Column("id",          sa.Integer(),     nullable=False),
            sa.Column("campaign_id", sa.Integer(),     nullable=False),
            sa.Column("user_id",     sa.Integer(),     nullable=True),
            sa.Column("email",       sa.String(254),   nullable=False),
            sa.Column("status",      sa.String(20),    nullable=False, server_default="pending"),
            sa.Column("provider_id", sa.String(200),   nullable=True),
            sa.Column("sent_at",     sa.DateTime(),    nullable=True),
            sa.Column("error",       sa.Text(),         nullable=True),
            sa.ForeignKeyConstraint(["campaign_id"], ["communication_campaigns.id"]),
            sa.ForeignKeyConstraint(["user_id"],     ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_communication_deliveries_campaign_id",
            "communication_deliveries",
            ["campaign_id"],
        )
        op.create_index(
            "ix_comms_delivery_campaign_status",
            "communication_deliveries",
            ["campaign_id", "status"],
        )


def downgrade():
    op.drop_index("ix_comms_delivery_campaign_status",           table_name="communication_deliveries")
    op.drop_index("ix_communication_deliveries_campaign_id",     table_name="communication_deliveries")
    op.drop_table("communication_deliveries")

    op.drop_index("ix_communication_campaigns_created_at",       table_name="communication_campaigns")
    op.drop_index("ix_communication_campaigns_status",           table_name="communication_campaigns")
    op.drop_table("communication_campaigns")

    try:
        op.drop_index("ix_users_comms_unsubscribe_token", table_name="users")
    except Exception:
        pass
    try:
        op.drop_constraint("uq_users_comms_unsubscribe_token", "users", type_="unique")
    except Exception:
        pass
    op.drop_column("users", "comms_unsubscribe_token")
    op.drop_column("users", "comms_opted_out")
