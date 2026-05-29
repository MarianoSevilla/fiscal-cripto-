"""add PayPal, billing, and quote fields to fiscal_advisory_requests

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-05-29 00:00:00.000000

Adds to fiscal_advisory_requests:
  Payment:
    - paypal_order_id         (String 64, nullable, indexed)
    - paypal_capture_id       (String 64, nullable)
    - payment_provider        (String 16, nullable) — 'paypal' | 'stripe'
    - paid_at                 (DateTime, nullable)
  Billing:
    - billing_nif             (String 20, nullable)
    - billing_address         (String 255, nullable)
    - billing_city            (String 100, nullable)
    - billing_postal_code     (String 20, nullable)
    - billing_company_name    (String 255, nullable)
  Quote (deferred payment flow):
    - quoted_amount           (Integer, nullable) — céntimos, precio fijado por admin
    - quoted_by_user_id       (FK users.id, nullable)
    - quote_message           (Text, nullable)
    - quote_sent_at           (DateTime, nullable)
    - quote_expires_at        (DateTime, nullable)
    - payment_link_token      (String 64, unique, indexed)
    - quote_accepted_at       (DateTime, nullable)
    - quote_acceptance_ip     (String 45, nullable)
    - quote_acceptance_user_agent (String 512, nullable)

Status migration:
  - Existing 'paid_received' rows without amount_paid → 'submitted'
    (they were "solicitud recibida" with no payment, mis-named from the start)
"""
from alembic import op
import sqlalchemy as sa


revision = "l5m6n7o8p9q0"
down_revision = "k4l5m6n7o8p9"
branch_labels = None
depends_on = None


def upgrade():
    # Payment fields
    op.add_column("fiscal_advisory_requests", sa.Column("paypal_order_id",      sa.String(64),  nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("paypal_capture_id",    sa.String(64),  nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("payment_provider",     sa.String(16),  nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("paid_at",              sa.DateTime(),  nullable=True))

    # Billing fields
    op.add_column("fiscal_advisory_requests", sa.Column("billing_nif",          sa.String(20),  nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("billing_address",      sa.String(255), nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("billing_city",         sa.String(100), nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("billing_postal_code",  sa.String(20),  nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("billing_company_name", sa.String(255), nullable=True))

    # Quote fields
    op.add_column("fiscal_advisory_requests", sa.Column("quoted_amount",              sa.Integer(),    nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("quoted_by_user_id",         sa.Integer(),    nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("quote_message",              sa.Text(),       nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("quote_sent_at",              sa.DateTime(),   nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("quote_expires_at",           sa.DateTime(),   nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("payment_link_token",         sa.String(64),   nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("quote_accepted_at",          sa.DateTime(),   nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("quote_acceptance_ip",        sa.String(45),   nullable=True))
    op.add_column("fiscal_advisory_requests", sa.Column("quote_acceptance_user_agent", sa.String(512), nullable=True))

    op.create_index("ix_fiscal_advisory_requests_paypal_order_id",    "fiscal_advisory_requests", ["paypal_order_id"])
    op.create_index("ix_fiscal_advisory_requests_payment_link_token", "fiscal_advisory_requests", ["payment_link_token"], unique=True)

    # Migrate existing data: rows that were created as 'paid_received' without a real payment
    # are semantically 'submitted' (the old code used paid_received as the initial state)
    op.execute("""
        UPDATE fiscal_advisory_requests
           SET status = 'submitted'
         WHERE status = 'paid_received'
           AND amount_paid IS NULL
    """)


def downgrade():
    op.execute("""
        UPDATE fiscal_advisory_requests
           SET status = 'paid_received'
         WHERE status = 'submitted'
    """)

    op.drop_index("ix_fiscal_advisory_requests_payment_link_token", table_name="fiscal_advisory_requests")
    op.drop_index("ix_fiscal_advisory_requests_paypal_order_id",    table_name="fiscal_advisory_requests")

    for col in [
        "quote_acceptance_user_agent", "quote_acceptance_ip", "quote_accepted_at",
        "payment_link_token", "quote_expires_at", "quote_sent_at",
        "quote_message", "quoted_by_user_id", "quoted_amount",
        "billing_company_name", "billing_postal_code", "billing_city",
        "billing_address", "billing_nif",
        "paid_at", "payment_provider", "paypal_capture_id", "paypal_order_id",
    ]:
        op.drop_column("fiscal_advisory_requests", col)
