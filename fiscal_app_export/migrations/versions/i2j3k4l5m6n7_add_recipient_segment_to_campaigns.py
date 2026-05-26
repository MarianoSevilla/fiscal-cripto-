"""add recipient_segment to communication_campaigns

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-05-26 00:00:00.000000

Adds:
  - communication_campaigns.recipient_segment  (String 20, default 'all')

Backfill logic:
  Campaigns already dispatched (sent/sending/queued/failed) ran under the
  old verified-only query, so they are backfilled to 'verified' for
  accurate history display.  New draft campaigns stay as 'all'.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision     = 'i2j3k4l5m6n7'
down_revision = 'h1i2j3k4l5m6'
branch_labels = None
depends_on    = None


def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    cols = {c["name"] for c in insp.get_columns("communication_campaigns")}

    if "recipient_segment" not in cols:
        op.add_column(
            "communication_campaigns",
            sa.Column(
                "recipient_segment",
                sa.String(20),
                nullable=False,
                server_default="all",
            ),
        )
        # Backfill: campaigns that were already dispatched ran under the
        # old verified-only query — mark them as 'verified' for accurate history.
        conn.execute(sa.text(
            "UPDATE communication_campaigns "
            "SET recipient_segment = 'verified' "
            "WHERE status IN ('sent', 'sending', 'queued', 'failed')"
        ))


def downgrade():
    op.drop_column("communication_campaigns", "recipient_segment")
