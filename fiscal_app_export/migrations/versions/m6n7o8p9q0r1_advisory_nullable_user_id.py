"""Allow NULL user_id on fiscal_advisory_requests (anonymous submissions)

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-05-30 00:00:00.000000

Motivation
----------
The advisory form (/pedir-asesoramiento) is now shown to all visitors,
including unauthenticated ones. The endpoint already assigns user_id=None
for anonymous sessions but the DB column was NOT NULL, causing an
IntegrityError on PostgreSQL for every anonymous submission.

Change
------
  fiscal_advisory_requests.user_id: nullable=False → nullable=True

Safety
------
- All existing rows have a valid user_id; no data is changed.
- Authenticated flow is unchanged: user_id is still set to current_user.id.
- Downgrade note: will raise IntegrityError at runtime if any row has
  user_id=NULL. Run only after removing anonymous rows or migrating them
  to a real user account.
"""

from alembic import op
import sqlalchemy as sa


revision      = "m6n7o8p9q0r1"
down_revision = "l5m6n7o8p9q0"
branch_labels = None
depends_on    = None


def upgrade():
    with op.batch_alter_table("fiscal_advisory_requests", schema=None) as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade():
    # NOTE: will fail at runtime if any row has user_id=NULL.
    with op.batch_alter_table("fiscal_advisory_requests", schema=None) as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
