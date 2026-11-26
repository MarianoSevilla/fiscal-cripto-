"""Persist FIFO credit execution claims and uncertain outcomes.

Revision ID: b4c5d6e7f8a9
Revises: a2b3c4d5e6f7

Additive only: no balances, reports, purchases, or existing analyses are
rewritten. Existing authorized reservations remain unstarted (`reserved`).
"""
from alembic import op


revision = "b4c5d6e7f8a9"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE credit_analyses "
        "ADD COLUMN IF NOT EXISTS execution_started_at TIMESTAMP NULL"
    )
    op.execute(
        "ALTER TABLE credit_analyses "
        "DROP CONSTRAINT ck_credit_analysis_status"
    )
    op.execute("""
        ALTER TABLE credit_analyses
        ADD CONSTRAINT ck_credit_analysis_status
        CHECK (status IN (
            'reserved','processing','consumed','released',
            'execution_unknown','settlement_unknown'
        ))
    """)


def downgrade():
    raise RuntimeError(
        "Credit execution history is financial evidence; destructive downgrade is prohibited"
    )
