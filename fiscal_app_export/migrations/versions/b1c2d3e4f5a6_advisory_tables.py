"""advisory tables

Revision ID: b1c2d3e4f5a6
Revises: 54699d21e348
Create Date: 2026-05-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = '54699d21e348'
branch_labels = None
depends_on = None


def upgrade():
    # Add role column to users
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(length=20), nullable=False, server_default='user'))

    # Create fiscal_advisory_requests table
    op.create_table(
        'fiscal_advisory_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('tax_residence_country', sa.String(length=100), nullable=False),
        sa.Column('tax_year', sa.Integer(), nullable=False),
        sa.Column('service_type', sa.String(length=50), nullable=False),
        sa.Column('operation_types', sa.Text(), nullable=True),
        sa.Column('exchanges', sa.Text(), nullable=True),
        sa.Column('operation_volume', sa.String(length=50), nullable=True),
        sa.Column('current_situation', sa.Text(), nullable=True),
        sa.Column('case_description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('stripe_checkout_session_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_payment_intent_id', sa.String(length=255), nullable=True),
        sa.Column('amount_paid', sa.Integer(), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('assigned_to', sa.Integer(), nullable=True),
        sa.Column('internal_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_checkout_session_id'),
    )
    op.create_index(op.f('ix_fiscal_advisory_requests_status'), 'fiscal_advisory_requests', ['status'], unique=False)
    op.create_index(op.f('ix_fiscal_advisory_requests_user_id'), 'fiscal_advisory_requests', ['user_id'], unique=False)

    # Create fiscal_advisory_files table
    op.create_table(
        'fiscal_advisory_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=512), nullable=False),
        sa.Column('file_type', sa.String(length=100), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['fiscal_advisory_requests.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_fiscal_advisory_files_request_id'), 'fiscal_advisory_files', ['request_id'], unique=False)

    # Create fiscal_advisory_status_history table
    op.create_table(
        'fiscal_advisory_status_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('changed_by', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['changed_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['request_id'], ['fiscal_advisory_requests.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_fiscal_advisory_status_history_request_id'), 'fiscal_advisory_status_history', ['request_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_fiscal_advisory_status_history_request_id'), table_name='fiscal_advisory_status_history')
    op.drop_table('fiscal_advisory_status_history')

    op.drop_index(op.f('ix_fiscal_advisory_files_request_id'), table_name='fiscal_advisory_files')
    op.drop_table('fiscal_advisory_files')

    op.drop_index(op.f('ix_fiscal_advisory_requests_user_id'), table_name='fiscal_advisory_requests')
    op.drop_index(op.f('ix_fiscal_advisory_requests_status'), table_name='fiscal_advisory_requests')
    op.drop_table('fiscal_advisory_requests')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('role')
