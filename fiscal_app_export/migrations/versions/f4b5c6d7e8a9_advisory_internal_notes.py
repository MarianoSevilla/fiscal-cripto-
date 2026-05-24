"""advisory internal notes table

Revision ID: f4b5c6d7e8a9
Revises: e2f3a4b5c6d7
Create Date: 2026-05-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision = 'f4b5c6d7e8a9'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    existing_tables = insp.get_table_names()

    if 'advisory_internal_notes' not in existing_tables:
        op.create_table(
            'advisory_internal_notes',
            sa.Column('id',          sa.Integer(),     nullable=False),
            sa.Column('request_id',  sa.Integer(),     nullable=False),
            sa.Column('author_id',   sa.Integer(),     nullable=True),
            sa.Column('author_name', sa.String(150),   nullable=True),
            sa.Column('text',        sa.Text(),         nullable=False),
            sa.Column('created_at',  sa.DateTime(),     nullable=False),
            sa.ForeignKeyConstraint(['request_id'], ['fiscal_advisory_requests.id'], ),
            sa.ForeignKeyConstraint(['author_id'],  ['users.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_advisory_internal_notes_request_id', 'advisory_internal_notes', ['request_id'])
        op.create_index('ix_advisory_internal_notes_created_at', 'advisory_internal_notes', ['created_at'])


def downgrade():
    op.drop_index('ix_advisory_internal_notes_created_at', table_name='advisory_internal_notes')
    op.drop_index('ix_advisory_internal_notes_request_id', table_name='advisory_internal_notes')
    op.drop_table('advisory_internal_notes')
